"""Compare the rebuilt solid with the imported original in the same CST project.

usage: py -3.12 tools/feat/compare_cst.py <port> <orig shape> <rebuild shape> <out_dir>

Writes <out_dir>/cnc_rebuild.sat (rebuild only) and <out_dir>/cnc_compare.tsv with
volumes, areas and the intersection volume (missing / extra material).
"""
import os
import sys

from rebuild_cst import vba


def copy_shape(name):
    return "\n".join([
        "With Transform", ".Reset", f'.Name "{name}"', '.Vector "0", "0", "0"', ".UsePickedPoints False",
        ".InvertPickedPoints False", ".MultipleObjects True", ".GroupObjects False", ".Repetitions 1",
        ".MultipleSelection False", '.Transform "Shape", "Translate"', "End With"])


def main(port, orig, rebuilt, out_dir):
    out = os.path.abspath(out_dir).replace("\\", "/")
    vba(port, "export rebuild", "\n".join([
        "With SAT", ".Reset", f'.FileName "{out}/cnc_rebuild.sat"', f'.Write "{rebuilt}"', "End With"]))
    vba(port, "compare: copies", copy_shape(orig) + "\n" + copy_shape(rebuilt))
    vba(port, "compare: intersect", f'Solid.Intersect "{orig}_1", "{rebuilt}_1"')
    vba(port, "compare: measure", "\n".join([
        f'Open "{out}/cnc_compare.tsv" For Output As #7',
        f'Print #7, "orig_volume" & Chr(9) & Solid.GetVolume("{orig}")',
        f'Print #7, "rebuild_volume" & Chr(9) & Solid.GetVolume("{rebuilt}")',
        f'Print #7, "common_volume" & Chr(9) & Solid.GetVolume("{orig}_1")',
        f'Print #7, "orig_area" & Chr(9) & Solid.GetArea("{orig}")',
        f'Print #7, "rebuild_area" & Chr(9) & Solid.GetArea("{rebuilt}")',
        "Close #7"]))
    print(open(f"{out}/cnc_compare.tsv").read())


if __name__ == "__main__":
    main(*sys.argv[1:5])
