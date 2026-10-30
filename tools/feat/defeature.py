"""Turn a SAT body into a 2.5-D prism body plus a list of finishing operations,
by undoing them one at a time in ACIS (agent in the CST modeler):

  1. blend / chamfer chains: api_remove_faces (neighbours extend to a sharp edge);
     records radius or setback and the boxes of the new sharp edges
  2. drafted walls: api_taper_faces to 0 deg about their neutral plane;
     records the angle and the boxes of the now-vertical faces

The ops list is written in removal order; replaying it backwards on the prism
rebuild restores the finishing. Faces/edges are located by bounding box only.

usage: py -3.12 tools/feat/defeature.py <modelerPid> <in.sat> <out_dir>
"""
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

import classify as C
import sat
from agent import Agent, Guard, box_dist, match

DRAFT_MAX = 10.0    # walls within this many degrees of vertical are drafts, steeper-than-that slopes are chamfers
BOX_TOL = 1e-6      # unchanged entities keep their box exactly


def neighbours(m):
    fidx = {f.index: i for i, f in enumerate(m.faces)}
    nb = defaultdict(set)
    for i, f in enumerate(m.faces):
        for lp in m.loops(f):
            for ce in m.coedges(lp):
                p = m.partner_face(ce)
                if p is not None and p in fidx and fidx[p] != i:
                    nb[i].add(fidx[p])
    return nb


def wall_angle(c, s):
    """Degrees from vertical for wall-like faces, else None."""
    if c == "slope":
        return 90 - math.degrees(math.acos(min(1, abs(s["normal"][2]))))
    if c in ("draft", "cone"):
        return math.degrees(math.atan2(abs(s["sine"]), abs(s["cosine"])))
    if c == "fillet_cyl" and abs(s["axis"][2]) > 0.5:
        return math.degrees(math.acos(min(1, abs(s["axis"][2]))))
    return None


def role(c, s):
    """finishing role of a face: 'fillet', 'chamfer', 'draft' or None (prismatic)."""
    if c in ("up", "down", "wall"):
        return None
    a = wall_angle(c, s)
    if a is not None and a < DRAFT_MAX:
        return "draft"
    if c in ("slope", "cone", "draft"):
        return "chamfer"
    return "fillet"


def radius_of(s):
    k = s["kind"]
    if k == "cone":
        return s["radius"]
    if k == "torus":
        return s["minor"]
    if k == "sphere":
        return s["radius"]
    return None


def components(ids, nb):
    ids, seen, out = set(ids), set(), []
    for i in ids:
        if i in seen:
            continue
        stack, comp = [i], []
        seen.add(i)
        while stack:
            j = stack.pop()
            comp.append(j)
            for k in nb[j]:
                if k in ids and k not in seen:
                    seen.add(k)
                    stack.append(k)
        out.append(sorted(comp))
    return out


def union_box(boxes, pad=0.0):
    return (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad, min(b[2] for b in boxes) - pad,
            max(b[3] for b in boxes) + pad, max(b[4] for b in boxes) + pad, max(b[5] for b in boxes) + pad)


def overlaps(a, b):
    return all(a[k] <= b[k + 3] and b[k] <= a[k + 3] for k in range(3))


def chamfer_setback(m, face, s):
    """Setback of a planar chamfer: its extent across the edge (approx. from the box)."""
    b = m.face_box(face)
    ext = sorted([b[3] - b[0], b[4] - b[1], b[5] - b[2]])
    return ext[0] if ext[0] > 1e-6 else ext[1]


def reach(boxes, pad=0.05):
    """Volume an operation on these faces can plausibly change (mm^3)."""
    return sum((b[3] - b[0] + pad) * (b[4] - b[1] + pad) * (b[5] - b[2] + pad) for b in boxes) + 0.01


def try_remove(ag, m, chain, kind):
    """One api_remove_faces call on `chain`; returns (op, status)."""
    faces = [m.faces[i] for i in chain]
    boxes = [m.face_box(f) for f in faces]
    idx = match(boxes, ag.boxes("faces"), 1e-3)
    if None in idx:
        return None, "not found (changed by an earlier step)"
    before = {b for _, b in ag.boxes("edges")}
    ok, r = ag.guard.run("rmfaces " + ag.ids(idx), reach(boxes))
    if not ok:
        return None, r
    region = union_box(boxes, 1e-3)
    op = {"op": kind, "faces": chain,
          "edges": [b for _, b in ag.boxes("edges") if b not in before and overlaps(b, region)]}
    if kind == "fillet":
        radii = [round(radius_of(m.surface(f)), 4) for f in faces if radius_of(m.surface(f))]
        op["radius"] = Counter(radii).most_common(1)[0][0] if radii else None
        op["radius_source"] = "surface" if radii else "none (spline-only chain)"
    else:
        op["setback"] = round(max(chamfer_setback(m, f, m.surface(f)) for f in faces), 4)
    return op, "removed"


def split(m, chain, nb):
    """Smaller pieces of a chain that would not go in one call: same-radius
    sub-chains first, single faces after that."""
    by_r = defaultdict(list)
    for i in chain:
        r = radius_of(m.surface(m.faces[i]))
        by_r[round(r, 4) if r else None].append(i)
    if len(by_r) > 1:
        return [c for ids in by_r.values() for c in components(ids, nb)]
    return [[i] for i in chain] if len(chain) > 1 else []


def remove_chains(ag, m, chains, kind, log, nb):
    ops, queue, n = [], list(chains), 0
    while queue:
        chain = queue.pop(0)
        op, status = try_remove(ag, m, chain, kind)
        if op:
            ops.append(op)
        else:
            parts = split(m, chain, nb)
            if parts:
                queue[:0] = parts
                status += f" -> split into {len(parts)}"
        log.append({"op": kind, "faces": chain, "status": status})
        n += 1
        if n % 20 == 0:
            print(f"  {kind}: {n} attempts, {len(ops)} removed, {len(queue)} queued", flush=True)
    return ops


def draft_groups(m, nb):
    """Connected drafted faces that rise from the same height the same way:
    (face ids, neutral z, {id: signed angle})."""
    info = {}
    for i, f in enumerate(m.faces):
        c, _, s = C.classify(m, f)
        if role(c, s) == "draft":
            nz = C.outward_normal(m, f, s)[2] if s["kind"] == "plane" else None
            info[i] = [wall_angle(c, s), m.face_box(f), nz]
    # corner faces (cones, tilted cylinders) take the lean of their planar neighbours
    for i, v in info.items():
        if v[2] is None:
            near = [info[j][2] for j in nb[i] if j in info and info[j][2] is not None]
            v[2] = sum(near) if near else 1.0
    key = {}
    for i, (a, b, nz) in info.items():
        up = nz >= 0
        key[i] = (up, round(b[2] if up else b[5], 3))
    out = []
    for k in set(key.values()):
        for comp in components([i for i in info if key[i] == k], nb):
            out.append((comp, k[1], {i: (1 if k[0] else -1) * round(info[i][0], 3) for i in comp}))
    return out


def halves(comp, nb):
    """Split a face set into two connected-ish halves (BFS order from one end)."""
    ids = set(comp)
    order, seen = [], {comp[0]}
    queue = [comp[0]]
    while queue:
        j = queue.pop(0)
        order.append(j)
        for k in nb[j]:
            if k in ids and k not in seen:
                seen.add(k)
                queue.append(k)
    order += [i for i in comp if i not in seen]
    h = len(order) // 2
    return [order[:h], order[h:]]


def untaper(ag, m, groups, log, pass_no, nb):
    ops, queue = [], list(groups)
    while queue:
        comp, zn, angles = queue.pop(0)
        boxes = [m.face_box(m.faces[i]) for i in comp]
        idx = match(boxes, ag.boxes("faces"), 1e-3)
        if None in idx:
            log.append({"op": "draft", "pass": pass_no, "faces": comp, "status": "not found"})
            continue
        ok, r = ag.guard.run(f"taper 0 0 {zn} 0 0 1 0 " + ag.ids(idx), reach(boxes))
        if not ok:
            if len(comp) > 1:
                parts = halves(comp, nb)
                queue[:0] = [(p, zn, {i: angles[i] for i in p}) for p in parts]
                r += " -> split into 2"
            log.append({"op": "draft", "pass": pass_no, "faces": comp, "status": r})
            continue
        # taper keeps the topology, so the same indices name the same faces
        after = dict(ag.boxes("faces"))
        ops.append({"op": "draft", "pass": pass_no, "neutral_z": round(zn, 6), "faces": comp,
                    "walls": [{"box": after[j], "angle_deg": angles[i]} for i, j in zip(comp, idx)]})
        log.append({"op": "draft", "pass": pass_no, "faces": comp, "status": "untapered"})
    return ops


def main(pid, src, out_dir, max_passes=6):
    t0 = time.time()
    out_dir = os.path.abspath(out_dir)
    ag = Agent(pid, os.path.join(out_dir, "defeature_tmp"))
    print(ag.cmd("restore " + os.path.abspath(src).replace(os.sep, "/")))
    ag.guard = Guard(ag)
    print(f"original volume {ag.guard.vol:.4f} mm3, box {ag.guard.box0}")
    cur = os.path.join(out_dir, "cnc_defeatured.sat").replace(os.sep, "/")
    log, ops, history = [], [], []
    m = sat.Model(src)
    for p in range(int(max_passes)):
        nb = neighbours(m)
        roles = Counter(role(*[C.classify(m, f)[k] for k in (0, 2)]) for f in m.faces)
        history.append({"pass": p, "faces": len(m.faces), "roles": {str(k): v for k, v in roles.items()}})
        print(f"pass {p}: {len(m.faces)} faces, roles {dict(roles)}", flush=True)
        n0 = len(ops)
        # fillets (incl. splines/tori/spheres) first, then chamfers, then drafts:
        # the reverse of the order a designer adds them
        for kind in ("fillet", "chamfer"):
            ids = [i for i, f in enumerate(m.faces) if role(*[C.classify(m, f)[k] for k in (0, 2)]) == kind]
            new = remove_chains(ag, m, components(ids, nb), kind, log, nb)
            for o in new:
                o["pass"] = p
            ops += new
        ag.cmd(f"save main {cur}")
        m = sat.Model(cur)
        nb2 = neighbours(m)
        ops += untaper(ag, m, draft_groups(m, nb2), log, p, nb2)
        ag.cmd(f"save main {cur}")
        m = sat.Model(cur)
        json.dump({"source": src, "ops": ops, "log": log, "passes": history},
                  open(os.path.join(out_dir, "cnc_defeature_ops.partial.json"), "w"), indent=1)
        print(f"pass {p}: {len(ops) - n0} ops", flush=True)
        if len(ops) == n0:
            break
    roles = Counter(role(*[C.classify(m, f)[k] for k in (0, 2)]) for f in m.faces)
    history.append({"pass": "final", "faces": len(m.faces), "roles": {str(k): v for k, v in roles.items()}})
    status = Counter((e["op"], e["status"] if e["status"] in ("removed", "untapered")
                      else "split" if "split into" in e["status"] else "failed") for e in log)
    res = {"source": src, "defeatured": cur, "seconds": round(time.time() - t0, 1), "passes": history,
           "summary": {f"{k[0]} {k[1]}": v for k, v in status.items()}, "ops": ops, "log": log}
    json.dump(res, open(os.path.join(out_dir, "cnc_defeature_ops.json"), "w"), indent=1)
    print(json.dumps({"summary": res["summary"], "final": history[-1]}, indent=1), f"{res['seconds']}s")


if __name__ == "__main__":
    main(*sys.argv[1:5])
