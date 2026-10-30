"""Replay a feature tree (tree.py JSON) in CST through the MCP HTTP server,
import the original SAT next to it, and measure volumes/areas.

usage: py -3.12 tools/feat/rebuild_cst.py <tree.json> <orig.sat> <port> <out_dir> [de_pid]

All CST work happens in the project the server is attached to; use a scratch
stack (cstmcp.py up --isolated). Values come back through files written by VBA,
since cst_vba returns nothing.
"""
import json
import os
import sys
import time
import urllib.request

CHUNK = 15


def call(port, tool, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", body,
                                 {"content-type": "application/json",
                                  "accept": "application/json, text/event-stream"})
    txt = urllib.request.urlopen(req, timeout=1800).read().decode()
    for line in txt.splitlines():
        if line.startswith("data:"):
            txt = line[5:]
    r = json.loads(txt)
    if "error" in r or r["result"].get("isError"):
        raise RuntimeError(f"{tool}: {r}")
    return r["result"]


def vba(port, header, code):
    return call(port, "cst_vba", {"header": header, "code": code})


def q(x):
    return f'"{x:.6f}"' if isinstance(x, float) else f'"{x}"'


def prism(name, ring, z0, h):
    pts = ring + [ring[0]]
    lines = ["With Extrude", ".Reset", f'.Name "{name}"', '.Component "rebuild"', '.Material "PEC"',
             '.Mode "pointlist"', f".Height {q(float(h))}", '.Twist "0.0"', '.Taper "0.0"',
             f'.Origin "0.0", "0.0", {q(float(z0))}', '.Uvector "1.0", "0.0", "0.0"', '.Vvector "0.0", "1.0", "0.0"',
             f".Point {q(float(pts[0][0]))}, {q(float(pts[0][1]))}"]
    lines += [f".LineTo {q(float(x))}, {q(float(y))}" for x, y in pts[1:]]
    lines += [".Create", "End With"]
    return "\n".join(lines)


def step(code, what):
    # remember the first failing statement of the current feature
    return f'{code}\nIf Err.Number <> 0 And firstErr = "" Then firstErr = "{what}: " & Err.Description\nErr.Clear'


SHRINK = [0.0, 2e-4, 1e-3]   # retry a failed cut with the profile pulled in this much (mm)


def attempt(ft, profile, tag):
    fid = ft["id"]
    name = f"f_{fid}"
    parts = [step(prism(name, profile["outer"], ft["z_from"], ft["depth"]), "outer")]
    inames = []
    for k, isl in enumerate(profile["islands"]):
        iname = f"i_{fid}_{k}"
        inames.append(iname)
        parts.append(step(prism(iname, isl, ft["z_from"], ft["depth"]), f"island {k}"))
        parts.append(step(f'Solid.Subtract "rebuild:{name}", "rebuild:{iname}"', f"island {k} subtract"))
    if ft["type"] != "stock":
        parts.append(step(f'Solid.Subtract "rebuild:f_stock", "rebuild:{name}"', "cut from stock"))
    # a failed attempt must not leave half-built solids behind
    cleanup = "\n".join(f'    Solid.Delete "rebuild:{n}"' for n in [name] + inames if n != "f_stock")
    return "\n".join([
        "If Not done Then",
        'firstErr = ""',
        *parts,
        '  If firstErr = "" Then',
        "    done = True",
        f'    used = "{tag}"',
        "  Else",
        f'    tried = tried & "{tag}: " & firstErr & "; "',
        cleanup,
        "    Err.Clear",
        "  End If",
        "End If",
    ])


def shrunk(profile, d):
    if d == 0:
        return profile
    from shapely.geometry import Polygon
    p = Polygon(profile["outer"], profile["islands"]).buffer(-d, join_style=2)
    if p.geom_type != "Polygon" or p.is_empty:
        return None
    return {"outer": [list(c) for c in p.exterior.coords[:-1]],
            "islands": [[list(c) for c in r.coords[:-1]] for r in p.interiors]}


def feature_code(ft, log):
    fid = ft["id"]
    tries = [(f"shrink {d * 1000:g}um", shrunk(ft["profile"], d)) for d in SHRINK]
    if ft["type"] == "stock":
        tries = tries[:1]
    parts = ["done = False", 'used = ""', 'tried = ""']
    parts += [attempt(ft, prof, tag) for tag, prof in tries if prof]
    parts += [
        'If tried <> "" Then',
        f'  Open "{log}" For Append As #9',
        f'  Print #9, "{fid}" & Chr(9) & IIf(done, "ok via " & used, "FAILED") & Chr(9) & tried',
        "  Close #9",
        "End If",
    ]
    return "\n".join(parts)


def probe_code(path):
    # every shape with its volume and area
    return "\n".join([
        f'Open "{path}" For Output As #8',
        "Dim i As Integer, nm As String",
        "For i = 0 To Solid.GetNumberOfShapes - 1",
        "  nm = Solid.GetNameOfShapeFromIndex(i)",
        '  Print #8, nm & Chr(9) & Solid.GetVolume(nm) & Chr(9) & Solid.GetArea(nm)',
        "Next i",
        "Close #8",
    ])


PAD_Z = 0.5      # cuts run this far past the stock top/bottom (mm)
PAD_XY = 0.05    # cuts grow this far outward, outside the footprint only (mm)


def padded(feats, z_top, z_bot):
    """Replay copies of the cut features that do not share faces with the stock:
    every cut runs out through the stock surface it is machined from (ancestors
    already remove that space) and pushes past the stock outline where it is
    open to the outside. Coincident faces make CST booleans fail."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    stock = [f for f in feats if f["type"] == "stock"]
    holes = [Polygon(f["profile"]["outer"]) for f in feats if f["type"] == "through_hole"]
    foot = unary_union([Polygon(f["profile"]["outer"]) for f in stock])
    foot = foot.difference(unary_union(holes)) if holes else foot
    out = []
    for f in feats:
        g = dict(f)
        if f["type"] == "stock":
            out.append(g)
            continue
        p = Polygon(f["profile"]["outer"], f["profile"]["islands"])
        grown = p.union(p.buffer(PAD_XY, join_style=2).difference(foot)).buffer(0)
        if grown.geom_type == "Polygon" and grown.is_valid:
            g["profile"] = {"outer": [list(c) for c in grown.exterior.coords[:-1]],
                            "islands": [[list(c) for c in r.coords[:-1]] for r in grown.interiors
                                        if Polygon(r).area > 1e-3]}
        if f["type"].startswith("top"):
            g["z_to"] = z_top + PAD_Z
        elif f["type"].startswith("bottom"):
            g["z_from"] = z_bot - PAD_Z
        else:
            g["z_from"], g["z_to"] = z_bot - PAD_Z, z_top + PAD_Z
        g["depth"] = g["z_to"] - g["z_from"]
        out.append(g)
    return out


def main(tree_path, sat_path, port, out_dir, de_pid=None):
    if de_pid:
        call(port, "cst_connect", {"mode": "pid", "pid": int(de_pid)})
    tree = json.load(open(tree_path))
    feats = padded(tree["features"], tree["z_top"], tree["z_bot"])
    log = os.path.abspath(os.path.join(out_dir, "cnc_rebuild_errors.tsv")).replace("\\", "/")
    open(log, "w").close()

    t0 = time.time()
    vba(port, "rebuild: setup", 'Component.New "rebuild"\nComponent.New "orig"')
    stock = [f for f in feats if f["type"] == "stock"]
    # parents before children: each cut then meets the simplest stock
    parent = {f["id"]: f["parent"] for f in feats}

    def level(fid):
        n = 0
        while parent.get(fid):
            fid, n = parent[fid], n + 1
        return n
    rest = sorted((f for f in feats if f["type"] != "stock"), key=lambda f: level(f["id"]))
    for i in range(0, len(stock + rest), CHUNK):
        chunk = (stock + rest)[i:i + CHUNK]
        code = ("On Error Resume Next\nDim firstErr As String, used As String, tried As String\n"
                "Dim done As Boolean\n" + "\n".join(feature_code(f, log) for f in chunk))
        vba(port, f"rebuild: features {i}-{i + len(chunk) - 1}", code)
        print(f"  features {i + len(chunk)}/{len(feats)}  {time.time() - t0:.0f}s", flush=True)

    sat = os.path.abspath(sat_path).replace("\\", "/")
    vba(port, "import original", "\n".join([
        "With SAT", ".Reset", f'.FileName "{sat}"', ".Id 1", ".ScaleToUnit False",
        ".ImportToActiveCoordinateSystem False", ".Read", "End With"]))

    shapes = os.path.abspath(os.path.join(out_dir, "cnc_rebuild_shapes.tsv")).replace("\\", "/")
    vba(port, "probe shapes", probe_code(shapes))
    print(open(shapes).read())
    print("errors:", open(log).read() or "none")
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(*sys.argv[1:6])
