"""Recognize pockets as machining operations and check the tool model against
the original surfaces.

A pocket machined from +Z (or -Z) with a bull-nose tool of corner radius r and
taper a leaves, seen in the (s, h) half-plane (s = plan distance outside the flat
floor region, h = height above the floor):

    floor  h = 0                      for s <= 0
    arc    centre (0, r), radius r    from (0, 0) to (r cos a, r (1 - sin a))
    wall   line from that point leaning outward by a

so the whole pocket follows from the flat region Fl at the floor level, r and a.
The vertical wall contour at the floor is Fl offset by r.

For every pocket the script fits (r, a) from the tool library and reports how
many of the surrounding original faces the model explains.

usage: py -3.12 tools/feat/machining.py <in.sat> <out.json>
"""
import json
import math
import sys
from collections import Counter, defaultdict

import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

import classify as C
import common
import draw
import sat
from tree import clean

TOL = 2e-3          # a face is explained when all its samples are this close to the model (mm)
ANGLES = [0, 1.5, 2, 2.5, 3, 5, 8]      # tapered tools seen in the part (deg)
MAX_R = 2.0         # larger concave radii are styling surfaces, not tool corners (mm)


def face_points(m, f, s):
    """Samples on a face: its boundary, plus the middle of cylinder faces."""
    pts = []
    for lp in m.loops(f):
        pts += C.loop_points(m, lp)
    if s["kind"] == "cone" and s.get("cylinder") and pts:
        a = np.array(s["axis"])
        c = np.array(s["point"])
        P = np.array(pts)
        d = P - c
        along = d @ a
        radial = d - np.outer(along, a)
        e1 = radial[0] / (np.linalg.norm(radial[0]) or 1)
        e2 = np.cross(a, e1)
        ang = np.arctan2(radial @ e2, radial @ e1)
        lo, hi = ang.min(), ang.max()
        if hi - lo < math.pi:               # fillets span < 180 deg
            mid = (lo + hi) / 2
            r = np.linalg.norm(radial, axis=1).mean()
            for t in np.linspace(along.min(), along.max(), 9):
                q = c + a * t + r * (math.cos(mid) * e1 + math.sin(mid) * e2)
                pts.append(list(q))
    return pts


def residual(sv, hv, r, a):
    """Distance of (s, h) samples to the tool profile."""
    a = math.radians(a)
    floor = np.where(sv <= 0, np.abs(hv), np.hypot(sv, hv))
    p1 = np.array([r * math.cos(a), r * (1 - math.sin(a))])
    if r > 0:
        phi = np.arctan2(hv - r, sv)
        on = (phi >= -math.pi / 2) & (phi <= -a)
        arc = np.where(on, np.abs(np.hypot(sv, hv - r) - r),
                       np.minimum(np.hypot(sv, hv), np.hypot(sv - p1[0], hv - p1[1])))
    else:
        arc = np.hypot(sv, hv)
    u = np.array([math.sin(a), math.cos(a)])
    t = np.maximum(0, (sv - p1[0]) * u[0] + (hv - p1[1]) * u[1])
    wall = np.hypot(sv - p1[0] - t * u[0], hv - p1[1] - t * u[1])
    return np.minimum(np.minimum(floor, arc), wall)


def wall_offset(h, r, a):
    """Plan offset of the model wall from Fl at height h (where the model can be)."""
    a = math.radians(a)
    return r * math.cos(a) + np.maximum(0.0, h - r * (1 - math.sin(a))) * math.tan(a)


def main(src, out):
    m = sat.Model(src)
    info = []
    for i, f in enumerate(m.faces):
        cls, z, s = C.classify(m, f)
        b = m.face_box(f)
        a = common.signed(m, f)
        info.append({"cls": cls, "z": z, "s": s, "box": b, "signed": a})

    concave_r = Counter()
    for i, f in enumerate(m.faces):
        s = info[i]["s"]
        if info[i]["cls"] == "fillet_cyl" and s["reversed"] and s["radius"] <= MAX_R:
            concave_r[round(s["radius"], 4)] += 1
    radii = [0.0] + sorted(concave_r)

    samples = {}

    def pts_of(i):
        if i not in samples:
            samples[i] = np.array(face_points(m, m.faces[i], info[i]["s"]))
        return samples[i]

    pockets = []
    for side, sgn in (("top", 1), ("bottom", -1)):
        # faces seen from this side, heights flipped so the tool always comes from +h
        mine = [i for i in range(len(m.faces)) if abs(info[i]["signed"]) > 1e-6
                and (info[i]["signed"] < 0) == (side == "top")]
        regions = {i: C.region(m, m.faces[i]) for i in mine}
        zmax = {i: max(sgn * info[i]["box"][2], sgn * info[i]["box"][5]) for i in mine}
        zmin = {i: min(sgn * info[i]["box"][2], sgn * info[i]["box"][5]) for i in mine}
        flat = [i for i in mine if info[i]["cls"] in ("up", "down")]
        levels = sorted({round(sgn * info[i]["z"], 4) for i in flat})
        top_level = levels[-1]
        for L in levels[:-1]:
            below = [i for i in mine if zmax[i] <= L + 1e-4]
            comps = clean(unary_union([regions[i] for i in below]))
            floors = [i for i in flat if abs(sgn * info[i]["z"] - L) < 1e-4]
            higher = [i for i in mine if zmin[i] > L + 1e-4]
            for comp in comps:
                pc = prep(comp.buffer(1e-3))
                fl = [i for i in floors if pc.intersects(regions[i].representative_point())]
                if not fl:
                    continue
                # through holes and child voids are cut by the tool too: fill holes
                # that no higher face of this side lies in
                keep = []
                for ring in comp.interiors:
                    hp = Polygon(ring)
                    hpp = prep(hp.buffer(-1e-3))
                    if any(hpp.intersects(regions[i].representative_point()) for i in higher):
                        keep.append(ring)
                Fl = Polygon(comp.exterior, keep)
                # candidate faces: above the floor, within 2.5 mm of the region
                zone = prep(Fl.buffer(2.5))
                cand = [i for i in range(len(m.faces))
                        if sgn * max(info[i]["box"][2], info[i]["box"][5]) > L + 1e-4
                        or (i in fl)]
                cand = [i for i in cand if min(sgn * info[i]["box"][2], sgn * info[i]["box"][5]) >= L - 1e-6
                        and zone.intersects(Point((info[i]["box"][0] + info[i]["box"][3]) / 2,
                                                  (info[i]["box"][1] + info[i]["box"][4]) / 2).buffer(
                            0.5 * max(info[i]["box"][3] - info[i]["box"][0], info[i]["box"][4] - info[i]["box"][1]) + 1e-3))]
                bnd = Fl.boundary
                per_face = {}
                for i in cand:
                    P = pts_of(i)
                    if not len(P):
                        continue
                    hv = sgn * P[:, 2] - L
                    sv = np.array([(-1 if Fl.contains(Point(x, y)) else 1) * bnd.distance(Point(x, y))
                                   for x, y in P[:, :2]])
                    per_face[i] = (sv, hv)
                # fit (r, a): the model must explain the faces touching the floor region
                best = None
                for r in radii:
                    for a in ANGLES:
                        exp_n, tot_n, area = 0, 0, 0.0
                        for i, (sv, hv) in per_face.items():
                            reach = wall_offset(hv, r, a) + 1e-3
                            inside = sv <= reach
                            if inside.mean() < 0.999:
                                continue        # face runs beyond the wall: another feature
                            tot_n += 1
                            if residual(sv, hv, r, a).max() <= TOL:
                                exp_n += 1
                        key = (2 * exp_n - tot_n, exp_n, -r)
                        if best is None or key > best[0]:
                            best = (key, r, a, exp_n, tot_n)
                _, r, a, exp_n, tot_n = best
                explained, unexplained = [], []
                for i, (sv, hv) in per_face.items():
                    reach = wall_offset(hv, r, a) + 1e-3
                    if (sv <= reach).mean() < 0.999:
                        continue
                    res = residual(sv, hv, r, a)
                    (explained if res.max() <= TOL else unexplained).append(
                        {"face": i, "kind": info[i]["cls"], "max_res": round(float(res.max()), 4)})
                pid = f"{side}{len(pockets)}"
                pockets.append({
                    "id": pid, "side": side, "floor_z": round(sgn * L, 4),
                    "floor_faces": fl, "area": round(Fl.area, 4),
                    "tool_corner_r": r, "taper_deg": a,
                    "faces_explained": len(explained), "faces_total": len(explained) + len(unexplained),
                    "explained": explained, "unexplained": unexplained,
                    "flat_region": {"outer": [list(map(float, p)) for p in Fl.exterior.coords[:-1]],
                                    "islands": [[list(map(float, p)) for p in r_.coords[:-1]] for r_ in Fl.interiors]},
                })
                print(f"{pid:10s} z={sgn * L:8.4f} area={Fl.area:8.3f} r={r:.4f} a={a:>4} "
                      f"explained {len(explained)}/{len(explained) + len(unexplained)}", flush=True)

    json.dump({"source": src, "tol_mm": TOL, "pockets": pockets}, open(out, "w"), indent=1)
    exp = sum(p["faces_explained"] for p in pockets)
    tot = sum(p["faces_total"] for p in pockets)
    print(json.dumps({"pockets": len(pockets), "faces_explained": exp, "faces_considered": tot}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
