"""Build hole-move tools: remove = original intersect new_void;
add = old_void minus new_void. Replaying these yields
(original union old_void) minus new_void without subtracting near-identical parts.

The caller must reconstruct the measured original void, bound its fill extent,
validate the new cutter and replay the result. No CST project/history is edited.
"""
import argparse
import json
import math
from pathlib import Path
import re

from local_delta import Pipe, difference_commands, native_path, reset_commands, validate_sat_paths


def command_plan(original, old_void, new_void):
    return {
        'remove': reset_commands() + ['restore ' + native_path(new_void), 'swap',
                                     'restore ' + native_path(original), 'bool int', 'faces'],
        'add': difference_commands(old_void, new_void),
    }


def generate(agent, original, old_void, new_void, out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {
        'status': 'running', 'original': native_path(original),
        'old_void': native_path(old_void), 'new_void': native_path(new_void),
        'target_definition': '(original union old_void) minus new_void',
        'warning': 'Validate old-void reconstruction and replay. The add tool is a pure increment only when old_void does not overlap original material. Native mass/bbox are diagnostic.',
        'bodies': {}, 'commands': [],
    }
    try:
        plan = command_plan(original, old_void, new_void)
        for name, commands in [('connection', ['ping']), *plan.items()]:
            last = ''
            for command in commands:
                entry = {'command': command}
                report['commands'].append(entry)
                last = agent.cmd(command)
                entry['reply'] = last
                if command.startswith('restore ') and not re.search(r'\bentities=1\b', last):
                    raise RuntimeError('restore must return exactly one entity: ' + last)
            if name == 'connection':
                continue
            match = re.search(r'\bfaces=(\d+)\b', last)
            if not match:
                raise RuntimeError('Missing face count: ' + last)
            count = int(match.group(1))
            body = {'faces': count, 'empty': count == 0, 'path': None}
            report['bodies'][name] = body
            if count:
                for key, command in [('mass_reply', 'mass'), ('bbox_reply', 'bbox'),
                                     ('save_reply', 'save main ' + native_path(out / (name + '.sat')))]:
                    entry = {'command': command}
                    report['commands'].append(entry)
                    reply = agent.cmd(command)
                    entry['reply'], body[key] = reply, reply
                body['path'] = native_path(out / (name + '.sat'))
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
    parser.add_argument('--old-void', type=Path, required=True)
    parser.add_argument('--new-void', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--dry-run', action='store_true', help='Validate inputs and print a plan; no files/IPC')
    args = parser.parse_args()
    try:
        if args.modeler_pid <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError('PID and timeout must be positive; timeout must be finite')
        validate_sat_paths((args.original, args.old_void, args.new_void), args.out)
        if args.dry_run:
            print(json.dumps(command_plan(args.original, args.old_void, args.new_void), indent=2))
        else:
            agent = Pipe(args.modeler_pid, args.timeout)
            try:
                report = generate(agent, args.original, args.old_void, args.new_void, args.out)
                print(json.dumps({'status': report['status'], 'bodies': report['bodies']}, indent=2))
            finally:
                agent.close()
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
