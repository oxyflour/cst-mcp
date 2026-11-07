"""Generate local remove/add SAT bodies in the existing ACIS scratch slots.

This does not import geometry into CST or modify its project history. The caller
must release the agent pipe, establish that bounds cover ALL changed geometry,
and verify/replay the output before applying it. --dry-run performs no IPC/writes.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time


def native_path(value):
    path = Path(value).resolve().as_posix()
    if not path.isascii() or any(c.isspace() for c in path) or '"' in path:
        raise ValueError('Use ASCII geometry paths without whitespace or quotes: ' + path)
    # The native request buffer is 1024 bytes; prism's profile field is 512.
    if len(path.encode('ascii')) > 480:
        raise ValueError('Geometry path is too long for native commands: ' + path)
    return path


def validate_sat_paths(inputs, out):
    """Validate single-body SAT inputs without creating output or touching CST."""
    if Path(out).exists():
        raise ValueError('Output directory must be new: ' + str(out))
    for value in (*inputs, out):
        native_path(value)
    repo = Path(__file__).resolve().parents[4]
    if str(repo / 'tools' / 'feat') not in sys.path:
        sys.path.insert(0, str(repo / 'tools' / 'feat'))
    from sat import load
    for value in inputs:
        if not Path(value).is_file():
            raise ValueError('Input SAT does not exist: ' + str(value))
        if sum(r.base == 'body' for r in load(str(value))) != 1:
            raise ValueError('Input must be a text SAT with exactly one BODY: ' + str(value))


def validate_inputs(original, modified, bounds, out):
    if len(bounds) != 6 or not all(math.isfinite(x) for x in bounds):
        raise ValueError('Bounds must be six finite model-unit coordinates')
    if any(bounds[i] >= bounds[i + 3] for i in range(3)):
        raise ValueError('Bounds must have min < max on every axis')
    if not math.isfinite(bounds[5] - bounds[2]):
        raise ValueError('Clip height overflows')
    validate_sat_paths((original, modified), out)


def profile_text(bounds):
    x0, y0, _, x1, y1, _ = bounds
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return ''.join('L %.17g %.17g %.17g %.17g\n' % (*a, *b)
                   for a, b in zip(points, points[1:]))


def reset_commands():
    # newbody clears main, not aux; clear both without deleting CST entities.
    return ['newbody', 'swap', 'newbody']


def clip_commands(source, bounds, profile):
    return reset_commands() + [
        'restore ' + native_path(source), 'swap',
        'prism new %.17g %.17g 0 %s' % (bounds[2], bounds[5] - bounds[2], native_path(profile)),
        'bool int', 'faces',
    ]


def difference_commands(main, tool):
    return reset_commands() + ['restore ' + native_path(tool), 'swap',
                               'restore ' + native_path(main), 'bool cut', 'faces']


class Pipe:
    """One fail-fast connection; bounded reads, no implicit retry or injection."""
    def __init__(self, pid, timeout):
        if os.name != 'nt':
            raise RuntimeError('Native execution requires Windows; --dry-run is offline')
        import ctypes
        import msvcrt
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.timeout = timeout
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.kernel.PeekNamedPipe.restype = wintypes.BOOL
        try:
            self.file = open('\\\\.\\pipe\\cst-acis-' + str(pid), 'r+b', buffering=0)
        except OSError as exc:
            raise RuntimeError('Cannot open agent pipe; release the existing owner connection first') from exc
        self.handle = msvcrt.get_osfhandle(self.file.fileno())

    def cmd(self, command):
        raw = (command + '\n').encode('ascii')
        if len(raw) > 1023 or '\n' in command or '\r' in command:
            raise ValueError('Invalid native command')
        self.file.write(raw)
        deadline, data = time.monotonic() + self.timeout, b''
        while not data.endswith(b'\n'):
            if time.monotonic() >= deadline:
                raise TimeoutError('Agent response timed out; native operation may still be running: ' + command)
            available = self.wintypes.DWORD()
            if not self.kernel.PeekNamedPipe(self.handle, None, 0, None, self.ctypes.byref(available), None):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            if available.value:
                chunk = self.file.read(min(available.value, 8192))
                if not chunk:
                    raise RuntimeError('Agent pipe closed during command: ' + command)
                data += chunk
                if len(data) > 32768:
                    raise RuntimeError('Unexpectedly large agent response')
            else:
                time.sleep(0.02)
        reply = data.decode('ascii').strip()
        if not reply.startswith('OK'):
            raise RuntimeError(command + ': ' + reply)
        return reply

    def close(self):
        self.file.close()


def generate(agent, original, modified, bounds, out):
    """Caller supplies an exclusively held pipe; outputs must not already exist."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    profile = out / 'clip.profile'
    profile.write_text(profile_text(bounds), encoding='ascii')
    report = {'status': 'running', 'original': native_path(original), 'modified': native_path(modified),
              'bounds_model_units': list(bounds), 'bodies': {}, 'commands': [],
              'warning': 'Local coverage is caller-supplied; mass/bbox replies are diagnostic approximations.'}

    def send(command):
        entry = {'command': command}
        report['commands'].append(entry)
        reply = agent.cmd(command)
        entry['reply'] = reply
        if command.startswith('restore ') and not re.search(r'\bentities=1\b', reply):
            raise RuntimeError('restore must return exactly one entity: ' + reply)
        return reply

    def perform(commands, name):
        last = ''
        for command in commands:
            last = send(command)
        match = re.search(r'\bfaces=(\d+)\b', last)
        if not match:
            raise RuntimeError('Missing face count: ' + last)
        count = int(match.group(1))
        body = {'faces': count, 'empty': count == 0, 'path': None}
        if count:
            body['mass_reply'] = send('mass')
            body['bbox_reply'] = send('bbox')
            body['path'] = native_path(out / (name + '.sat'))
            send('save main ' + body['path'])
        report['bodies'][name] = body
        return body

    try:
        send('ping')
        before = perform(clip_commands(original, bounds, profile), 'original_local')
        after = perform(clip_commands(modified, bounds, profile), 'modified_local')
        for name, main, tool in [('remove', before, after), ('add', after, before)]:
            if main['empty']:
                report['bodies'][name] = {'faces': 0, 'empty': True, 'path': None}
            elif tool['empty']:
                perform(reset_commands() + ['restore ' + main['path'], 'faces'], name)
            else:
                perform(difference_commands(main['path'], tool['path']), name)
        report['status'] = 'complete'
        return report
    except Exception as exc:
        report['status'], report['error'] = 'failed', str(exc)
        raise
    finally:
        (out / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modeler-pid', type=int, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--modified', type=Path, required=True)
    parser.add_argument('--bounds', nargs=6, type=float, required=True,
                        metavar=('XMIN', 'YMIN', 'ZMIN', 'XMAX', 'YMAX', 'ZMAX'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120,
                        help='Per-command response timeout; does not cancel native work (default: 120s)')
    parser.add_argument('--dry-run', action='store_true', help='Validate inputs and print a plan; no files/IPC')
    args = parser.parse_args()
    try:
        if args.modeler_pid <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError('PID and timeout must be positive; timeout must be finite')
        validate_inputs(args.original, args.modified, args.bounds, args.out)
        if args.dry_run:
            print(json.dumps({
                'modeler_pid': args.modeler_pid, 'bounds_model_units': args.bounds,
                'original_clip': clip_commands(args.original, args.bounds, args.out / 'clip.profile'),
                'modified_clip': clip_commands(args.modified, args.bounds, args.out / 'clip.profile'),
                'remove_if_both_nonempty': difference_commands(args.out / 'original_local.sat', args.out / 'modified_local.sat'),
                'add_if_both_nonempty': difference_commands(args.out / 'modified_local.sat', args.out / 'original_local.sat'),
                'output': native_path(args.out),
            }, indent=2))
        else:
            agent = Pipe(args.modeler_pid, args.timeout)
            try:
                report = generate(agent, args.original, args.modified, args.bounds, args.out)
                print(json.dumps({'status': report['status'], 'bodies': report['bodies']}, indent=2))
            finally:
                agent.close()
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
