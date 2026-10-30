"""Rebuild a part in ACIS (agent in the CST modeler) from
  - a prism feature tree of the defeatured body (tree.py on cnc_defeatured.sat)
  - the finishing ops recorded by defeature.py, applied in reverse order.

Profiles go to the agent as exact lines and arcs: polygon runs that lie on a
vertical cylinder of the defeatured body are turned back into arcs.

usage: py -3.12 tools/feat/replay_acis.py <modelerPid> <tree.json> <ops.json> <defeatured.sat> <out.sat> [base]

base=defeatured skips the prisms and replays the ops on the defeatured body
itself, which separates finishing-op problems from prism-rebuild problems.
"""
import json
import math
import os
import sys
import time
from collections import Counter

import classify as C
import sat
from agent import Agent, box_dist
from rebuild_cst import padded

ON_CIRCLE = 6e-4    # a profile point this close to a wall cylinder lies on it (mm)
MAX_STEP = 1.2      # larger angular steps between two on-circle points are chords, not arcs (rad)


def wall_circles(m):
    out = []
    for f in m.faces:
        c, _, s = C.classify(m, f)
        if c == "wall" and s["kind"] == "cone":
            # vertical cylinder: centre in plan from the axis point
            out.append((s["point"][0], s["point"][1], s["radius"]))
    return list({(round(x, 6), round(y, 6), round(r, 6)) for x, y, r in out})


def on_circle(p, circles):
    best = None
    for c in circles:
        d = abs(math.hypot(p[0] - c[0], p[1] - c[1]) - c[2])
        if d < ON_CIRCLE and (best is None or d < best[0]):
            best = (d, c)
    return best[1] if best else None


def ring_segments(ring, circles):
    """Closed ring -> list of ('L', x1,y1,x2,y2) / ('A', x1,y1,xm,ym,x2,y2)."""
    pts = [tuple(p) for p in ring]
    n = len(pts)
    circ = [on_circle(p, circles) for p in pts]

    def arc_step(i):
        a, b = pts[i], pts[(i + 1) % n]
        c = circ[i]
        if c is None or c != circ[(i + 1) % n]:
            return None
        t0 = math.atan2(a[1] - c[1], a[0] - c[0])
        t1 = math.atan2(b[1] - c[1], b[0] - c[0])
        d = (t1 - t0 + math.pi) % (2 * math.pi) - math.pi
        return (c, d) if 1e-9 < abs(d) < MAX_STEP else None

    steps = [arc_step(i) for i in range(n)]
    # start at a point where the kind changes so runs do not wrap around
    start = next((i for i in range(n) if steps[i] is None or steps[i - 1] is None
                  or steps[i][0] != steps[i - 1][0] or (steps[i][1] > 0) != (steps[i - 1][1] > 0)), 0)
    segs, i = [], 0
    while i < n:
        k = (start + i) % n
        st = steps[k]
        if st is None:
            a, b = pts[k], pts[(k + 1) % n]
            if math.dist(a, b) > 1e-6:
                segs.append(("L", a[0], a[1], b[0], b[1]))
            i += 1
            continue
        c, d = st
        total, j = 0.0, i
        while j < n:
            sj = steps[(start + j) % n]
            if sj is None or sj[0] != c or (sj[1] > 0) != (d > 0) or abs(total + sj[1]) > 2 * math.pi - 0.2:
                break
            total += sj[1]
            j += 1
        a = pts[k]
        b = pts[(start + j) % n]
        t0 = math.atan2(a[1] - c[1], a[0] - c[0])
        tm = t0 + total / 2
        mid = (c[0] + c[2] * math.cos(tm), c[1] + c[2] * math.sin(tm))
        segs.append(("A", a[0], a[1], mid[0], mid[1], b[0], b[1]))
        i = j
    return segs


MAX_BLEND = 5.0    # larger "fillets" are styling surfaces; not replayed as edge blends (mm)
FIT_TOL = 2e-3     # max distance of a run's points from the fitted line/arc (mm)
MAX_RUN = 400


def circle3(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def line_fits(pts):
    a, b = pts[0], pts[-1]
    L = math.dist(a, b)
    if L < 1e-9:
        return False
    return all(abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / L <= FIT_TOL for p in pts[1:-1])


def arc_fits(pts):
    c = circle3(pts[0], pts[len(pts) // 2], pts[-1])
    if not c or c[2] > 200:
        return None
    if any(abs(math.hypot(p[0] - c[0], p[1] - c[1]) - c[2]) > FIT_TOL for p in pts):
        return None
    # the polyline between samples must hug the arc too: a long straight run
    # ending in a few corner points fits a large circle at its vertices only
    if any(c[2] - math.sqrt(max(0.0, c[2] ** 2 - math.dist(pts[i], pts[i + 1]) ** 2 / 4)) > FIT_TOL
           for i in range(len(pts) - 1)):
        return None
    # monotonic sweep, no step a chord would hide
    ang = [math.atan2(p[1] - c[1], p[0] - c[0]) for p in pts]
    steps = [(ang[i + 1] - ang[i] + math.pi) % (2 * math.pi) - math.pi for i in range(len(ang) - 1)]
    if not (all(s > 0 for s in steps) or all(s < 0 for s in steps)) or max(abs(s) for s in steps) > MAX_STEP:
        return None
    if abs(sum(steps)) > 2 * math.pi - 0.2:
        return None
    return c, ang[0] + sum(steps) / 2


def refit(segs):
    """Turn runs of short lines back into the longest lines and arcs that fit."""
    out, run = [], []

    def flush():
        pts = run
        i = 0
        while i < len(pts) - 1:
            best = ("L", i + 1, None)
            for j in range(min(len(pts) - 1, i + MAX_RUN), i + 1, -1):
                if line_fits(pts[i:j + 1]):
                    best = ("L", j, None)
                    break
            for j in range(min(len(pts) - 1, i + MAX_RUN), max(best[1], i + 2) - 1, -1):
                if j - i >= 3:
                    fit = arc_fits(pts[i:j + 1])
                    if fit and j > best[1]:
                        best = ("A", j, fit)
                        break
            kind, j, fit = best
            a, b = pts[i], pts[j]
            if kind == "L":
                out.append(("L", a[0], a[1], b[0], b[1]))
            else:
                (cx, cy, r), tm = fit
                out.append(("A", a[0], a[1], cx + r * math.cos(tm), cy + r * math.sin(tm), b[0], b[1]))
            i = j

    for s in segs:
        if s[0] == "L":
            if not run:
                run = [(s[1], s[2])]
            run.append((s[3], s[4]))
        else:
            if run:
                flush()
                run = []
            out.append(s)
    if run:
        flush()
    return out


def write_profile(path, profile, circles):
    with open(path, "w") as f:
        for k, ring in enumerate([profile["outer"]] + profile["islands"]):
            if k:
                f.write("LOOP\n")
            for s in refit(ring_segments(ring, circles)):
                f.write(s[0] + " " + " ".join(f"{v:.9f}" for v in s[1:]) + "\n")


def find(current, targets, tol=2e-3):
    """Indices of current entities matching target boxes: exact-ish box match, else
    entities whose box lies inside a target box (split edges/faces)."""
    hits = set()
    for t in targets:
        best = min(current, key=lambda c: box_dist(c[1], t))
        if box_dist(best[1], t) <= tol:
            hits.add(best[0])
            continue
        for i, b in current:
            if all(b[k] >= t[k] - tol for k in range(3)) and all(b[k + 3] <= t[k + 3] + tol for k in range(3)):
                hits.add(i)
    return sorted(hits)


def main(pid, tree_path, ops_path, defeatured, out_sat, base="prisms"):
    t0 = time.time()
    out_sat = os.path.abspath(out_sat)    # the agent resolves paths in the modeler's cwd
    tree = json.load(open(tree_path))
    ops = json.load(open(ops_path))["ops"]
    circles = wall_circles(sat.Model(defeatured))
    out_dir = os.path.dirname(os.path.abspath(out_sat))
    ag = Agent(pid, os.path.join(out_dir, "replay_tmp"))
    prof = f"{ag.scratch}/profile.txt"

    feats = padded(tree["features"], tree["z_top"], tree["z_bot"])
    parent = {f["id"]: f["parent"] for f in feats}

    def level(fid):
        n = 0
        while parent.get(fid):
            fid, n = parent[fid], n + 1
        return n
    order = [f for f in feats if f["type"] == "stock"] + sorted(
        (f for f in feats if f["type"] != "stock"), key=lambda f: level(f["id"]))

    log = []
    ag.cmd("newbody")
    if base == "defeatured":
        ag.cmd("restore " + os.path.abspath(defeatured).replace(os.sep, "/"))
        order = []
    for k, ft in enumerate(order):
        write_profile(prof, ft["profile"], circles)
        op = "new" if ft["type"] == "stock" else "cut"
        r = ag.cmd(f"prism {op} {ft['z_from']} {ft['depth']} 0 {prof}", check=False)
        log.append({"step": "prism", "id": ft["id"], "result": r})
        if k % 25 == 0:
            print(f"  prisms {k + 1}/{len(order)}  {time.time() - t0:.0f}s  {r}", flush=True)
    ag.cmd(f"save main {out_sat.replace(os.sep, '/')}.prisms.sat")

    for k, op in enumerate(reversed(ops)):
        if op["op"] == "draft":
            # one taper per angle; walls of a ring can lean by different amounts
            by_angle = {}
            for w in op["walls"]:
                by_angle.setdefault(w["angle_deg"], []).append(w["box"])
            results = []
            for ang, boxes in by_angle.items():
                idx = find(ag.boxes("faces"), boxes)
                r = ag.cmd(f"taper 0 0 {op['neutral_z']} 0 0 1 {ang} " + ag.ids(idx), check=False)                     if idx else "ERR no matching faces"
                results.append(r)
            ok = all(r.startswith("OK") for r in results)
            log.append({"step": "draft", "faces": op["faces"], "result": "OK" if ok else "; ".join(results)})
            continue
        elif op["op"] == "chamfer":
            idx = find(ag.boxes("edges"), op["edges"])
            cmd = f"chamfer {op['setback']} {op['setback']} " + ag.ids(idx)
        else:
            if not op.get("radius"):
                log.append({"step": "fillet", "faces": op["faces"], "result": "skipped: no radius"})
                continue
            if op["radius"] > MAX_BLEND:
                # styling surfaces, not edge rounds; api_blend_edges can spin for ever on them
                log.append({"step": "fillet", "faces": op["faces"], "result": f"skipped: radius {op['radius']} > {MAX_BLEND}"})
                continue
            idx = find(ag.boxes("edges"), op["edges"])
            cmd = f"blend {op['radius']} " + ag.ids(idx)
        r = ag.cmd(cmd, check=False) if idx else "ERR no matching entities"
        log.append({"step": op["op"], "faces": op["faces"], "matched": len(idx), "result": r})
        if k % 25 == 0:
            print(f"  ops {k + 1}/{len(ops)}  {time.time() - t0:.0f}s  {op['op']}: {r}", flush=True)

    ag.cmd(f"save main {out_sat.replace(os.sep, '/')}")
    summary = Counter((e["step"], "ok" if e["result"].startswith("OK") else "failed") for e in log)
    res = {"seconds": round(time.time() - t0, 1), "summary": {f"{a} {b}": v for (a, b), v in summary.items()},
           "log": log}
    json.dump(res, open(out_sat + ".log.json", "w"), indent=1)
    print(json.dumps(res["summary"], indent=1), f"{res['seconds']}s")


if __name__ == "__main__":
    main(*sys.argv[1:7])
