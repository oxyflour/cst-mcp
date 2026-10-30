"""Cross-check the classifier's fillet faces against ACIS api_detect_blends
(agent `detect blend <i>` on every face).

usage: py -3.12 tools/feat/blend_check.py <modelerPid> <in.sat> <tree.json> <out.json>

Face indices from the agent follow api_get_faces order; that order matches the
SAT face record order for a freshly restored body (checked via face counts and
the agreement table this script prints).
"""
import json
import os
import sys
from collections import Counter

from voxel_compare import pipe_cmd


def main(pid, src, tree_path, out):
    tree = json.load(open(tree_path))
    cls = {}
    for kind, faces in tree["finishing"]["faces"].items():
        for e in faces:
            cls[e["face"]] = kind
    f = open("//./pipe/cst-acis-" + str(pid), "r+b", buffering=0)
    r = pipe_cmd(f, "restore " + os.path.abspath(src).replace(os.sep, "/"))
    n = int(r.split("faces=")[1])
    acis = {}
    for i in range(n):
        f.write(f"detect blend {i}\n".encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += f.read(4096)
        acis[i] = buf.decode().startswith("OK")
    table = Counter((cls.get(i, "up/down/wall"), acis[i]) for i in range(n))
    rows = sorted({k for k, _ in table})
    res = {"faces": n,
           "by_class": {k: {"acis_blend": table[(k, True)], "acis_not_blend": table[(k, False)]} for k in rows},
           "acis_blend_faces": [i for i in range(n) if acis[i]]}
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res["by_class"], indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
