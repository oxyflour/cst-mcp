"""Machining-model test on single pockets: build each pocket's tool body on its
own and compare it with the original where the two can be compared without
coincident faces.

For each pocket recognized by machining.py (flat floor region Fl, tool corner
radius r, taper a):
  T = prism of the wall contour (Fl offset by r), floor .. rim + PAD, floor edges
      blended with r: the swept volume of the tool. The blend runs on this small
      prism alone, never on the part.
  K = probe slab: wall contour shrunk by DELTA, from DELTA above the floor to DELTA
      under the rim. It holds the void of the pocket and the material the tool
      leaves in its corners (fillets), and touches none of the pocket's faces.
  compare  vol(O * K)  (original material in the slab)
     with  vol(K - T)  (material the tool leaves in the slab)
  and vol(T) with the volume the tool profile predicts.

usage: py -3.12 tools/feat/tool_pockets.py <modelerPid> <in.sat> <machining.json> <out_dir> id...
"""
import json
import math
import os
import sys
import time

from shapely.geometry import Polygon

import sat
from agent import Agent
from replay_acis import refit

DELTA = 1e-3        # probe slab clearance from the pocket's floor, walls and rim (mm)
PAD = 0.3           # the tool body runs this far past the rim (mm)
UNDER = [2e-4, 2e-3]    # blend this much under r, in turn: where the contour corner radius equals
                        # r (ball corners) the exact blend is a torus of zero major radius,
                        # which ACIS refuses (mm)
SIMPLIFY = 1e-3     # contour simplification before refitting lines/arcs; chords shorter than
                    # the blend radius make api_blend_edges fail to cap (mm)


def write_profile(path, C):
    with open(path, "w") as f:
        for k, ring in enumerate([C.exterior] + list(C.interiors)):
            if k:
                f.write("LOOP\n")
            pts = list(ring.simplify(SIMPLIFY).coords)
            for s in refit([("L",) + tuple(a) + tuple(b) for a, b in zip(pts[:-1], pts[1:])]):
                f.write(s[0] + " " + " ".join(f"{v:.9f}" for v in s[1:]) + "\n")


def floor_offset(r, a):
    """Plan offset from the flat floor region to the drafted wall line at floor height."""
    a = math.radians(a)
    return r * math.cos(a) - r * (1 - math.sin(a)) * math.tan(a)


def model_volume(Fl, r, a, H, n=60):
    """Volume of the tool body predicted by the profile, floor .. H above it."""
    ar = math.radians(a)

    def off(h):
        if h < r * (1 - math.sin(ar)):
            return math.sqrt(max(0.0, r * r - (r - h) ** 2))
        return r * math.cos(ar) + (h - r * (1 - math.sin(ar))) * math.tan(ar)
    hs = [H * k / n for k in range(n + 1)]
    if r > 0:     # finer through the arc
        hs = sorted(set(hs + [r * k / 40 for k in range(41) if r * k / 40 < H]))
    areas = [Fl.buffer(off(h), quad_segs=64).area if off(h) > 0 else Fl.area for h in hs]
    return sum((hs[k + 1] - hs[k]) * (areas[k] + areas[k + 1]) / 2 for k in range(len(hs) - 1))


def main(pid, src, mjson, out_dir, *ids):
    src = os.path.abspath(src).replace(os.sep, "/")
    out_dir = os.path.abspath(out_dir)
    m = sat.Model(src)
    pockets = {p["id"]: p for p in json.load(open(mjson))["pockets"]}
    ag = Agent(pid, os.path.join(out_dir, "toolpk_tmp"))
    prof = f"{ag.scratch}/profile.txt"
    results = []
    for pid_ in ids:
        p = pockets[pid_]
        t0 = time.time()
        sgn = 1 if p["side"] == "top" else -1
        L = p["floor_z"]
        r, a = p["tool_corner_r"], p["taper_deg"]
        rim = max(sgn * z for e in p["explained"] for z in (m.face_box(m.faces[e["face"]])[2],
                                                                m.face_box(m.faces[e["face"]])[5]))
        H = rim - sgn * L
        Fl = Polygon(p["flat_region"]["outer"], p["flat_region"]["islands"])
        s0 = floor_offset(r, a)
        C = Fl.buffer(s0, quad_segs=64) if s0 > 0 else Fl
        write_profile(prof, C)
        write_profile(prof + ".slab", C.buffer(-DELTA, quad_segs=64))
        res = {"id": pid_, "side": p["side"], "floor_z": L, "rim_height_mm": round(H, 4), "r": r, "taper": a,
               "contour_area": round(C.area, 4), "contour_segments": sum(1 for _ in open(prof))}

        def step(name, line):
            rr = ag.cmd(line, check=False)
            res[name] = rr
            if not rr.startswith("OK"):
                raise RuntimeError(f"{name}: {rr}")
            return rr

        def vol():
            rr = ag.cmd("mass", check=False)
            return float(rr.split("volume=")[1]) if rr.startswith("OK") else 0.0
        slab = f"prism new {L + sgn * DELTA} {sgn * (H - 2 * DELTA)} {a} {prof}.slab"
        try:
            # tool body alone
            ag.cmd("newbody")
            step("tool_prism", f"prism new {L} {sgn * (H + PAD)} {a} {prof}")
            if r > 0:
                edges = [i for i, b in ag.boxes("edges") if abs(b[2] - L) < 1e-6 and abs(b[5] - L) < 1e-6]
                for under in UNDER:
                    rr = ag.cmd(f"blend {r - under} " + ag.ids(edges), check=False)
                    res.setdefault("blend_tries", []).append(rr[:80])
                    if rr.startswith("OK"):
                        break
                if not rr.startswith("OK"):
                    raise RuntimeError(f"tool_blend: {rr}")
                res["blend_r"] = r - under
                res["blended_edges"] = len(edges)
            VT = vol()
            VT_model = model_volume(Fl, r, a, H + PAD)
            res.update({"V_tool": VT, "V_tool_model": VT_model, "tool_vs_model": VT - VT_model})
            ag.cmd(f"save main {(out_dir + '/toolpk_' + pid_ + '_tool.sat').replace(os.sep, '/')}")
            # K - T  (tool goes to aux, slab becomes main)
            step("swap_t", "swap")
            step("slab_new", slab)
            VK = vol()
            step("slab_minus_tool", "bool cut")
            V_new = vol()
            # O * K
            ag.cmd("newbody")
            step("slab_ref", slab)
            step("swap_k", "swap")
            step("restore", "restore " + src)
            step("orig_times_slab", "bool int")
            V_ref = vol()
            res.update({"ok": True, "V_slab": VK, "V_left_by_tool": V_new, "V_original_in_slab": V_ref,
                        "left_minus_original": V_new - V_ref})
        except RuntimeError as e:
            res.update({"ok": False, "error": str(e)})
        res["seconds"] = round(time.time() - t0, 1)
        results.append(res)
        print(json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in res.items()
                          if not k.startswith(("swap", "slab", "restore", "orig", "tool_prism"))}), flush=True)
    json.dump(results, open(os.path.join(out_dir, "toolpk_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
