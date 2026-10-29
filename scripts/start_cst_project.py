"""Start a CST Design Environment with a fresh Microwave Studio project.

Keeps the DE alive after this script exits (it is a separate process). Used to
get a live modeler_AMD64.exe so the ACIS probe has somewhere to land.
"""
from __future__ import print_function

import sys
import time

import cst.interface as ci

print("running DEs before:", ci.running_design_environments())
de = ci.DesignEnvironment.new()
print("started DE pid:", de.pid())

deadline = time.time() + 180
prj = None
while time.time() < deadline:
    try:
        prj = de.new_mws()
        break
    except Exception as exc:
        print("  waiting for DE to accept projects: %s" % (exc,))
        time.sleep(5)

if prj is None:
    print("FAILED: DE never became usable")
    sys.exit(1)

print("project:", prj.filename())
print("connected pids:", ci.running_design_environments())
