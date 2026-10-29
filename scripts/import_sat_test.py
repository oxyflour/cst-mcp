"""Import a SAT file that the injected ACIS payload produced.

The VBA command is the one CST records when you import through the GUI
(Modeling: Exchange > Import > 3D Files > ACIS SAT/SAB):

    With SAT
         .Reset
         .FileName "<path>"
         .Id "1"
         .Version "9.0"
         .ScaleToUnit "0"
         .ImportToActiveCoordinateSystem "True"
         .Curves "True"
         .Read
    End With

Note: `Import` is not a CST object; the method is `SAT.Read`.
"""
from __future__ import print_function

import os
import sys

import cst.interface as ci


def sat_import_code(path, item_id="1"):
    return (
        "With SAT\n"
        "     .Reset\n"
        '     .FileName "%s"\n'
        '     .Id "%s"\n'
        '     .Version "9.0"\n'
        '     .ScaleToUnit "0"\n'
        '     .ImportToActiveCoordinateSystem "True"\n'
        '     .Curves "True"\n'
        "     .Read\n"
        "End With" % (path, item_id)
    )


def main():
    temp = os.environ.get("TEMP", r"C:\Temp")
    files = sys.argv[1:] or [
        os.path.join(temp, "cst_acis_block.sat"),
        os.path.join(temp, "cst_acis_sheet.sat"),
    ]

    de = ci.DesignEnvironment.connect_to_any()
    de.set_quiet_mode(True)
    modeler = de.active_project().modeler
    print("project:", de.active_project().filename())

    for i, path in enumerate(files, start=1):
        if not os.path.exists(path):
            print("[skip] missing", path)
            continue
        modeler.add_to_history("sat_import_%d" % i, sat_import_code(path, str(i)))
        print("[ok] %s (%d bytes)" % (path, os.path.getsize(path)))

    print("imported; check the 3D view")


if __name__ == "__main__":
    main()
