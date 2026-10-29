"""Diagnose the CST automation path before wiring anything else up.

Run with CST's *bundled* interpreter (the .pyd is cp36..cp39 only):

    "C:\\Programs\\CST Studio Suite 2022\\AMD64\\python\\python.exe" scripts\\probe_cst.py
    ... scripts\\probe_cst.py --run "With Brick\n...\nEnd With"

Open a Design Environment first. The probe never starts one, so it cannot
consume a licence.
"""

from __future__ import print_function

import argparse
import sys
import traceback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="VBA snippet to execute in the active project")
    ap.add_argument("--pid", type=int, help="attach to this PID instead of any DE")
    args = ap.parse_args()

    print("python      :", sys.version.split()[0])

    try:
        import cst.interface as ci
    except Exception:
        traceback.print_exc()
        print("\nFAILED to import cst.interface. Use the bundled python.exe.")
        return 2

    print("cst libs    :", ci.__file__)
    pids = ci.running_design_environments()
    print("running DEs :", pids)

    if not pids:
        print("\nNo Design Environment is running. Start CST, open a project, rerun.")
        return 1

    de = ci.DesignEnvironment.connect(args.pid) if args.pid else ci.DesignEnvironment.connect_to_any()
    print("attached    : pid=%s version=%s" % (de.pid(), ci.DesignEnvironment.version()))
    print("projects    :", de.list_open_projects())

    if not de.has_active_project():
        print("\nNo active project. Open one and rerun.")
        return 1

    prj = de.active_project()
    print("active      :", prj.filename())
    print("folder      :", prj.folder())

    modeler = prj.modeler
    if modeler is None:
        print("active project has no 3D modeler (schematic project?)")
        return 0

    print("solver      : running=%s name=%s" % (modeler.is_solver_running(), modeler.get_active_solver_name()))

    if args.run:
        print("\n-- executing VBA --")
        modeler.add_to_history("mcp-probe", args.run)
        print("ok")

    return 0


if __name__ == "__main__":
    sys.exit(main())
