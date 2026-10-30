"""Render a SAT body's edges in three orthographic views (PNG)."""
import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sat


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def edge_points(m, e):
    p0 = m.vertex_pos(e.ptr(4))
    p1 = m.vertex_pos(e.ptr(6))
    c = m.rec(e.ptr(9))
    if c is not None and c.base == "intcurve":
        pts = sat.intcurve_points(m, c, 200)
        if not pts:
            return [p0, p1]
        i0 = min(range(len(pts)), key=lambda i: math.dist(pts[i], p0))
        i1 = min(range(len(pts)), key=lambda i: math.dist(pts[i], p1))
        if e.ptr(4) == e.ptr(6):          # closed edge: whole curve
            i0, i1 = 0, len(pts) - 1
        seg = pts[i0:i1 + 1] if i0 <= i1 else pts[i1:i0 + 1][::-1]
        return [p0] + seg[1:-1][::4] + [p1]
    if c is None or c.base != "ellipse":
        return [p0, p1]
    ctr, n, maj = c.nums(4, 3), sat.unit(c.nums(7, 3)), c.nums(10, 3)
    ratio = float(c.f[13])
    minor = [x * ratio for x in cross(n, maj)]
    # end parameters from the vertices themselves; the stored edge parameters
    # only tell how far the edge runs (conventions differ between writers)
    def param(p):
        d = [p[i] - ctr[i] for i in range(3)]
        mm = sum(x * x for x in maj)
        nn = sum(x * x for x in minor)
        return math.atan2(sum(d[i] * minor[i] for i in range(3)) / nn, sum(d[i] * maj[i] for i in range(3)) / mm)
    span = abs(float(e.f[7]) - float(e.f[5]))
    t0, t1 = param(p0), param(p1)
    ccw = (t1 - t0) % (2 * math.pi)
    if e.ptr(4) == e.ptr(6) or ccw < 1e-9:
        t1 = t0 + 2 * math.pi
    elif abs(ccw - span) <= abs((2 * math.pi - ccw) - span):
        t1 = t0 + ccw
    else:
        t1 = t0 - (2 * math.pi - ccw)
    k = max(4, int(abs(t1 - t0) / 0.15))
    return [[ctr[i] + maj[i] * math.cos(t) + minor[i] * math.sin(t) for i in range(3)]
            for t in (t0 + (t1 - t0) * j / k for j in range(k + 1))]


def main(path, out, faces=None):
    m = sat.Model(path)
    edges = [x for x in m.r if x.base == "edge"]
    polys = [edge_points(m, e) for e in edges]
    fig, ax = plt.subplots(3, 1, figsize=(16, 13), gridspec_kw={"height_ratios": [2.2, 1, 1]})
    for a, (i, j, name) in zip(ax, [(0, 1, "top (X-Y)"), (0, 2, "front (X-Z)"), (1, 2, "side (Y-Z)")]):
        for p in polys:
            a.plot([q[i] for q in p], [q[j] for q in p], lw=0.35, color="k")
        a.set_aspect("equal")
        a.set_title(name)
    fig.tight_layout()
    fig.savefig(out, dpi=110)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
