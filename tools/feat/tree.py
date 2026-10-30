"""Recover a 2.5-D machining feature tree (machining axis Z) from a SAT body.

Model: every vertical line through the part meets material in one interval
[b(x,y), t(x,y)]. Up-facing faces tile the plan view with heights t, down-facing
faces with heights b. Then

    body = stock(footprint, z_bot..z_top)
         - top pockets    (level sets {t <= L}, nested by containment)
         - bottom pockets (level sets {b >= L})

Non-horizontal faces (fillets, chamfers, splines) are snapped to the nearest
real floor level of the same side and listed separately as finishing features.

usage: py -3.12 tools/feat/tree.py <in.sat> <out.json> [crack_mm]

crack_mm closes gaps between neighbouring face regions up to twice that width
(default 2e-4; edges ACIS stores only in a surface parameter space are drawn as
chords and leave wider gaps)
"""
import json
import math
import sys
from collections import defaultdict

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

import classify as C
import common
import sat

EPS = 2e-4       # crack closing between adjacent faces (mm)
PINCH = 1e-4     # opens rings that touch themselves at a point (mm)
SIMPLIFY = 5e-4  # profile simplification tolerance (mm)
MIN_AREA = 1e-3  # drop slivers below this (mm^2)


def clean(geom):
    """Close cracks between faces, split rings that touch themselves (CST will not
    extrude them), drop sliver islands, thin out sub-micron segments."""
    g = geom.buffer(EPS, join_style=2).buffer(-EPS, join_style=2)
    g = g.buffer(-PINCH, join_style=2).buffer(PINCH, join_style=2)
    g = g.simplify(SIMPLIFY)
    out = []
    for p in ([g] if isinstance(g, Polygon) else list(getattr(g, "geoms", []))):
        if not isinstance(p, Polygon) or p.area <= MIN_AREA:
            continue
        p = Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area > MIN_AREA])
        if not p.is_valid:
            p = make_valid(p)
            out += [q for q in getattr(p, "geoms", [p]) if isinstance(q, Polygon) and q.area > MIN_AREA]
        else:
            out.append(p)
    return out


def ring(r):
    pts = [(round(x, 5), round(y, 5)) for x, y in r.coords[:-1]]
    return [list(p) for p in pts]


def shape_of(poly):
    """Name the profile: circle (with diameter) or polygon."""
    ext = Polygon(poly.exterior)
    roundness = 4 * math.pi * ext.area / ext.length ** 2
    if roundness > 0.995:
        return {"shape": "circle", "diameter": round(2 * math.sqrt(ext.area / math.pi), 4),
                "center": [round(ext.centroid.x, 4), round(ext.centroid.y, 4)]}
    return {"shape": "polygon", "vertices": len(poly.exterior.coords) - 1}


def snap(h, levels):
    return min(levels, key=lambda L: abs(L - h)) if levels else h


def level_tree(cells, top_side, z_far):
    """cells: [(region, height, face_ids)]. top_side: pockets cut from +Z.
    Returns pocket nodes with profile, z range and parent links."""
    sgn = 1 if top_side else -1
    levels = sorted({h for _, h, _ in cells}, key=lambda h: sgn * h)  # deepest first
    by_level = defaultdict(list)
    for reg, h, ids in cells:
        by_level[h].append((reg, ids))
    nodes, acc, acc_ids, prev = [], [], [], []
    for k, L in enumerate(levels):
        for reg, ids in by_level[L]:
            acc.append(reg)
            acc_ids.append((reg, ids))
        nxt = levels[k + 1] if k + 1 < len(levels) else z_far
        comps = clean(unary_union(acc))
        cur = []
        for c in comps:
            node = None
            # a lower-level component inside c with the same area continues as one pocket
            kids = [n for n in prev if c.buffer(10 * EPS).contains(n["_poly"])]
            if len(kids) == 1 and abs(kids[0]["_poly"].area - c.area) < 1e-3:
                node = kids[0]
            else:
                node = {"_poly": c, "_kids": kids, "floor": L}
                for kd in kids:
                    kd["_parent"] = node
                nodes.append(node)
            node["ceiling"] = nxt
            cur.append(node)
        prev = cur
    return nodes, levels


def main(src, out, crack=None):
    global EPS
    if crack:
        EPS = float(crack)
    m = sat.Model(src)
    tops, bots, finishing = [], [], defaultdict(list)
    for idx, f in enumerate(m.faces):
        cls, z, s = C.classify(m, f)
        if cls not in ("up", "down", "wall"):
            entry = {"face": idx, "kind": cls}
            if s["kind"] == "cone":
                entry["radius"] = round(s["radius"], 4)
            if s["kind"] == "torus":
                entry["radius"] = round(s["minor"], 4)
                entry["major"] = round(s["major"], 4)
            if s["kind"] == "sphere":
                entry["radius"] = round(s["radius"], 4)
            if s["kind"] == "plane":
                entry["slope_deg"] = round(math.degrees(math.acos(min(1, abs(s["normal"][2])))), 2)
            finishing[cls].append(entry)
        a = common.signed(m, f)
        if abs(a) < 1e-6:
            continue
        b = m.face_box(f)
        h = z if z is not None else (b[2] + b[5]) / 2
        (tops if a < 0 else bots).append((C.region(m, f), h, idx, z is not None))

    top_levels = sorted({round(h, 4) for _, h, _, flat in tops if flat})
    bot_levels = sorted({round(h, 4) for _, h, _, flat in bots if flat})
    tcells = [(r, round(h, 4) if flat else snap(h, top_levels), [i]) for r, h, i, flat in tops]
    bcells = [(r, round(h, 4) if flat else snap(h, bot_levels), [i]) for r, h, i, flat in bots]
    z_top, z_bot = max(top_levels), min(bot_levels)

    footprint = clean(unary_union([r for r, _, _ in tcells]))
    tnodes, _ = level_tree(tcells, True, z_top)
    bnodes, _ = level_tree(bcells, False, z_bot)

    feats = []
    for p in footprint:
        feats.append({"id": "stock", "type": "stock", "op": "add", "parent": None,
                      "z_from": z_bot, "z_to": z_top, "_poly": Polygon(p.exterior)})
        for k, hole in enumerate(p.interiors):
            hp = Polygon(hole)
            feats.append({"id": f"through{k}", "type": "through_hole", "op": "cut", "parent": "stock",
                          "z_from": z_bot, "z_to": z_top, "_poly": hp})

    def emit(nodes, side):
        name = {}
        for n in nodes:
            if n["floor"] == n["ceiling"]:
                continue
            nid = f"{side}{len(name)}"
            name[id(n)] = nid
        for n in nodes:
            if id(n) not in name:
                continue
            par = n.get("_parent")
            while par is not None and id(par) not in name:
                par = par.get("_parent")
            z0, z1 = sorted((n["floor"], n["ceiling"]))
            feats.append({"id": name[id(n)], "type": f"{side}_pocket", "op": "cut",
                          "parent": name[id(par)] if par is not None else "stock",
                          "z_from": z0, "z_to": z1, "_poly": n["_poly"]})

    emit(tnodes, "top")
    emit(bnodes, "bottom")

    vol = 0.0
    for ft in feats:
        p = ft.pop("_poly")
        ft["depth"] = round(ft["z_to"] - ft["z_from"], 4)
        ft["area"] = round(p.area, 4)
        ft.update(shape_of(p))
        ft["profile"] = {"outer": ring(p.exterior), "islands": [ring(i) for i in p.interiors]}
        if ft["shape"] == "circle" and ft["type"].endswith("pocket"):
            ft["type"] = "top_hole" if ft["type"].startswith("top") else "bottom_hole"
        vol += (1 if ft["op"] == "add" else -1) * p.area * ft["depth"]

    radii = defaultdict(int)
    for cls in ("fillet_cyl", "fillet_torus", "fillet_sphere"):
        for e in finishing[cls]:
            radii[e["radius"]] += 1
    tree = {
        "source": src, "units": "mm", "axis": "Z", "method": "2.5D depth-level decomposition",
        "z_top": z_top, "z_bot": z_bot, "faces": len(m.faces),
        "predicted_volume": round(vol, 4),
        "features": feats,
        "finishing": {
            "summary": {k: len(v) for k, v in finishing.items()},
            "fillet_radii": dict(sorted(radii.items(), key=lambda kv: -kv[1])),
            "faces": finishing,
            "replayed": False,
        },
    }
    with open(out, "w") as fp:
        json.dump(tree, fp, indent=1)
    by = defaultdict(int)
    for ft in feats:
        by[ft["type"]] += 1
    print(json.dumps({"features": len(feats), "by_type": by, "predicted_volume": tree["predicted_volume"],
                      "z": [z_bot, z_top], "finishing": tree["finishing"]["summary"]}))


if __name__ == "__main__":
    main(*sys.argv[1:4])
