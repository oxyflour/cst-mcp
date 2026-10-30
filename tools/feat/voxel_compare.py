"""Compare two SAT bodies by classifying the same point grid against each inside
the CST modeler (agent `pgrid`, api_point_in_body). No booleans involved, so
near-coincident faces do not matter.

usage: py -3.12 tools/feat/voxel_compare.py <modelerPid> <a.sat> <b.sat> <out_prefix> [h_xy] [h_z]

Writes <out_prefix>.json (volumes, missing/extra material) and <out_prefix>.png
(plan-view map of where the bodies differ).
"""
import json
import math
import os
import sys
import time

import numpy as np

import sat

SLAB = 40          # x columns per agent call (keeps each job well under its 900 s limit)
INSIDE, BOUNDARY = 1, 2


def pipe_cmd(f, cmd):
    f.write((cmd + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        buf += f.read(4096)
    r = buf.decode().strip()
    if not r.startswith("OK"):
        raise RuntimeError(f"{cmd!r}: {r}")
    return r


def classify(f, path, grid, tmp):
    x0, y0, z0, h, hz, nx, ny, nz = grid
    pipe_cmd(f, f"restore {path}")
    out = np.empty((nx, ny, nz), np.uint8)
    t = time.time()
    for i in range(0, nx, SLAB):
        n = min(SLAB, nx - i)
        pipe_cmd(f, f"pgrid {x0 + i * h} {y0} {z0} {h} {h} {hz} {n} {ny} {nz} {tmp}")
        out[i:i + n] = np.fromfile(tmp, np.uint8).reshape(n, ny, nz)
        print(f"  {os.path.basename(path)}: {i + n}/{nx} columns  {time.time() - t:.0f}s", flush=True)
    return out


def main(pid, a_sat, b_sat, prefix, h=0.3, hz=0.15):
    h, hz = float(h), float(hz)
    a_abs, b_abs = (os.path.abspath(p).replace(os.sep, "/") for p in (a_sat, b_sat))
    body = sat.load(a_sat)[0]                     # first record is the body, with its box
    lo, hi = body.nums(body.f.index("T") + 1, 3), body.nums(body.f.index("T") + 4, 3)
    # offset the grid off round numbers so points do not sit on model planes
    x0, y0, z0 = lo[0] + h * 0.437, lo[1] + h * 0.437, lo[2] + hz * 0.437
    nx, ny, nz = (int(math.ceil((hi[k] - lo[k]) / s)) for k, s in ((0, h), (1, h), (2, hz)))
    grid = (x0, y0, z0, h, hz, nx, ny, nz)
    tmp = os.path.abspath(prefix + ".slab.bin").replace(os.sep, "/")
    f = open("//./pipe/cst-acis-" + str(pid), "r+b", buffering=0)
    A = classify(f, a_abs, grid, tmp)
    B = classify(f, b_abs, grid, tmp)
    os.remove(tmp)

    cell = h * h * hz
    ina, inb = A == INSIDE, B == INSIDE
    miss, extra = ina & ~inb, inb & ~ina
    res = {
        "a": a_sat, "b": b_sat, "grid_mm": [h, h, hz], "points": int(A.size),
        "a_volume_est": round(float(ina.sum() * cell), 3),
        "b_volume_est": round(float(inb.sum() * cell), 3),
        "missing_in_b": round(float(miss.sum() * cell), 3),
        "extra_in_b": round(float(extra.sum() * cell), 3),
        "boundary_or_unknown_points": int(((A != INSIDE) & (A != 3)).sum() + ((B != INSIDE) & (B != 3)).sum()),
    }
    res["symmetric_difference"] = round(res["missing_in_b"] + res["extra_in_b"], 3)
    res["symmetric_difference_pct_of_a"] = round(100 * res["symmetric_difference"] / res["a_volume_est"], 3)
    np.savez_compressed(prefix + ".npz", A=A, B=B, grid=np.array(grid))
    json.dump(res, open(prefix + ".json", "w"), indent=1)
    print(json.dumps(res, indent=1))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ext = [x0, x0 + nx * h, y0, y0 + ny * h]
    fig, ax = plt.subplots(2, 1, figsize=(16, 8.5))
    for a, d, title, cmap in ((ax[0], miss, "material missing in rebuild (mm, column thickness)", "Reds"),
                              (ax[1], extra, "extra material in rebuild (mm, column thickness)", "Blues")):
        im = a.imshow(d.sum(axis=2).T * hz, origin="lower", extent=ext, cmap=cmap, vmin=0,
                      vmax=max(hz, float(np.percentile(d.sum(axis=2)[d.sum(axis=2) > 0] * hz, 99)) if d.any() else hz))
        a.contour(np.linspace(ext[0], ext[1], nx), np.linspace(ext[2], ext[3], ny), ina.any(axis=2).T,
                  levels=[0.5], colors="0.6", linewidths=0.6)
        a.set_title(title)
        a.set_aspect("equal")
        fig.colorbar(im, ax=a, fraction=0.02)
    fig.tight_layout()
    fig.savefig(prefix + ".png", dpi=110)


if __name__ == "__main__":
    main(*sys.argv[1:7])
