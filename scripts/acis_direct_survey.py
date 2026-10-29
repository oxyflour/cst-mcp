"""Inventory the ACIS API families that correspond to "direct modelling"."""
from __future__ import print_function

import collections
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(HERE, "..", "out", "SpaACIS.full.exports.txt")

FAMILIES = [
    # face/edge local edits
    "offset_face", "offset_body", "offset_surface", "offset_curve",
    "sweep_face", "rotate_face", "translate_face", "tweak",
    "remove_face", "cover_face", "replace_face", "delete_face",
    "taper", "draft", "deformable", "deform",
    # teardown / rebuild
    "hollow", "shell", "simplify", "defeature", "heal", "clean",
    "imprint", "split", "trim", "separate",
    # booleans and blends
    "boolean", "blend", "chamfer", "fillet",
    # topology construction
    "sweep", "loft", "skin", "cover", "stitch", "sew",
    # queries
    "mass_prop", "get_face", "get_edge", "get_coedges", "entity_extrema",
]


def main():
    lines = open(EXPORTS).read().splitlines()
    api = [l for l in lines if l.startswith("?api_")]
    print("total exports %d, api_* %d" % (len(lines), len(api)))

    seen = set()
    for fam in FAMILIES:
        hits = [l for l in api if fam in l]
        names = set()
        for h in hits:
            m = re.match(r"\?([A-Za-z0-9_]+)@@", h)
            if m:
                names.add(m.group(1))
        if not names:
            continue
        key = tuple(sorted(names))
        if key in seen:
            continue
        seen.add(key)
        print("\n### %-16s %d symbols" % (fam, len(names)))
        for n in sorted(names)[:14]:
            print("   ", n)
        if len(names) > 14:
            print("    ...")

    inits = sorted({re.match(r"\?([A-Za-z0-9_]+)@@", l).group(1)
                    for l in api if l.startswith("?api_initialize_")})
    print("\n### api_initialize_* components (%d)" % len(inits))
    print("   ", ", ".join(x.replace("api_initialize_", "") for x in inits))


if __name__ == "__main__":
    main()
