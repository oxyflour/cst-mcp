"""Start a brand-new Design Environment and a project in it.

Prints one JSON line: {"de_pid": N, "project": "..."}.
Always creates a new DE — never attaches to an existing one.
"""
from __future__ import print_function

import json
import sys

import cst.interface as ci


def main():
    before = ci.running_design_environments()
    de = ci.DesignEnvironment.new()
    prj = de.new_mws()
    print(json.dumps({"de_pid": de.pid(), "project": prj.filename(), "before": before}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
