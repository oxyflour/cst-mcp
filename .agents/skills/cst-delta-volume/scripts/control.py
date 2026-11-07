"""Run a guarded temporary CST control macro. Use CST's bundled Python 3.6.

Serialise with the owner. This bypasses model history, so use it for queries and
owned scratch geometry; apply the final edit through cst_vba instead.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--de-pid', type=int, required=True)
    parser.add_argument('--project', required=True, help='Exact active project path to guard')
    parser.add_argument('--code', type=Path, required=True, help='UTF-8 VBA statements inside Sub Main')
    parser.add_argument('--output', type=Path, required=True, help='New JSON result file')
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args()
    if args.de_pid <= 0 or args.timeout <= 0:
        parser.error('PID and timeout must be positive')
    if args.output.exists():
        parser.error('Output JSON already exists')
    repo = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo / 'bridge'))
    import cst.interface as ci
    from live_brep import execute_control_macro
    de = ci.DesignEnvironment.connect(args.de_pid)
    project = de.active_project()
    if os.path.normcase(os.path.abspath(project.filename())) != os.path.normcase(os.path.abspath(args.project)):
        raise RuntimeError('Active project changed: ' + project.filename())
    quiet = de.in_quiet_mode()
    timed_out = []

    class Schematic:
        def execute_vba_code(self, code):
            try:
                project.schematic.execute_vba_code(code, timeout=args.timeout)
            except TimeoutError:
                timed_out.append(True)
                # execute_control_macro still requires a complete BEGIN/END response.

    class Project:
        schematic = Schematic()

    code = '''Sub Main
Dim fh As Integer
fh = FreeFile
Open "PIPE_NAME" For Output As #fh
Print #fh, "BEGIN" & vbTab & "delta"
On Error GoTo Failed
SNIPPET
Print #fh, "END"
Close #fh
Exit Sub
Failed:
Print #fh, "ERROR" & vbTab & CStr(Err.Number) & vbTab & Err.Description
Print #fh, "END"
Close #fh
End Sub
'''.replace('SNIPPET', args.code.read_text(encoding='utf-8'))
    try:
        de.set_quiet_mode(True)
        lines = execute_control_macro(Project(), code)
        result = {'lines': lines, 'interface_timed_out': bool(timed_out),
                  'macro_error': any(s.startswith('ERROR\t') for s in lines)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=True))
        return 1 if result['macro_error'] else 0
    finally:
        de.set_quiet_mode(quiet)


if __name__ == '__main__':
    sys.exit(main())
