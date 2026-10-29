"""Start a CST Design Environment with a fresh 3D (Microwave Studio) project.

The ACIS modeler (modeler_AMD64.exe) only exists while a 3D project is open, and
that is the process we inject the ACIS agent into. Prints DE_PID / MWS_OK so the
caller can poll for the modeler before injecting.
"""
import sys
import time

import cst.interface as ci


def main() -> int:
    de = ci.DesignEnvironment.new()
    print("DE_PID=%d" % de.pid(), flush=True)
    try:
        de.set_quiet_mode(True)
    except Exception as exc:  # quiet mode is a nicety, not a requirement
        print("quiet-mode failed: %r" % (exc,), flush=True)

    prj = de.new_mws()
    print("MWS_OK %s" % (prj,), flush=True)
    # Keep the handle alive briefly; the DE itself outlives this script.
    time.sleep(10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
