"""Minimal ACIS SAT (text, v7+) reader: records, topology walk, analytic surfaces.

Only what feature recognition needs. Subtype blocks ({ ... }) are kept as raw
tokens; spline geometry is not evaluated.
"""
import math
import re

_TOK = re.compile(r"@(\d+) |\S+")


def _tokens(text, pos):
    while True:
        m = _TOK.search(text, pos)
        if not m:
            return
        if m.group(1) is not None:          # length-prefixed string
            n = int(m.group(1))
            yield ("str", text[m.end():m.end() + n])
            pos = m.end() + n
        else:
            yield ("tok", m.group(0))
            pos = m.end()


class Record:
    __slots__ = ("index", "type", "f")

    def __init__(self, index, type_, fields):
        self.index, self.type, self.f = index, type_, fields

    def ptr(self, i):
        t = self.f[i]
        return int(t[1:]) if t.startswith("$") else None

    def nums(self, i, n):
        return [float(x) for x in self.f[i:i + n]]

    @property
    def base(self):
        return self.type.split("-")[0]


def load(path):
    text = open(path, encoding="latin-1").read()
    # header: 3 lines, plus a "T @n ..." line in recent versions
    lines = text.split("\n", 4)
    start = len(lines[0]) + len(lines[1]) + len(lines[2]) + 3
    if lines[3].startswith("T "):
        start += len(lines[3]) + 1
    recs, cur = [], None
    for kind, tok in _tokens(text, start):
        if cur is None:
            if tok.startswith("End-of-"):
                break
            cur = [tok]
        elif kind == "tok" and tok == "#":
            recs.append(Record(len(recs), cur[0], cur[1:]))
            cur = None
        else:
            cur.append(tok)
    return recs


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n else v


class Model:
    def __init__(self, path):
        self.r = load(path)
        self.faces = [x for x in self.r if x.base == "face"]

    def rec(self, p):
        return self.r[p] if p is not None and p >= 0 else None

    def surface(self, face):
        s = self.rec(face.ptr(8))
        reversed_ = face.f[9] == "reversed"
        t, f = s.base, s.f
        d = {"kind": t, "reversed": reversed_}
        if t == "plane":
            d.update(point=s.nums(4, 3), normal=unit(s.nums(7, 3)))
        elif t == "cone":
            major = s.nums(10, 3)
            ratio = float(f[13])
            i = 14
            for _ in range(2):                 # u-range: I or F <v>
                i += 1 if f[i] == "I" else 2
            sine, cosine, scale = float(f[i]), float(f[i + 1]), float(f[i + 2])
            d.update(point=s.nums(4, 3), axis=unit(s.nums(7, 3)),
                     radius=math.sqrt(sum(c * c for c in major)), ratio=ratio,
                     sine=sine, cosine=cosine, cylinder=abs(sine) < 1e-9,
                     surf_sense=f[i + 3])
        elif t == "torus":
            d.update(center=s.nums(4, 3), axis=unit(s.nums(7, 3)),
                     major=float(f[10]), minor=float(f[11]))
        elif t == "sphere":
            d.update(center=s.nums(4, 3), radius=abs(float(f[7])))
        elif t == "spline":
            d.update(subtype=f[f.index("{") + 1] if "{" in f else "?")
        return d

    def box(self, rec, at):
        # "T x0 y0 z0 x1 y1 z1" box after the given field index
        if at < len(rec.f) and rec.f[at] == "T":
            return rec.nums(at + 1, 6)
        return None

    def face_box(self, face):
        return self.box(face, 11)

    def loops(self, face):
        out, lp = [], self.rec(face.ptr(5))
        while lp:
            out.append(lp)
            lp = self.rec(lp.ptr(4))
        return out

    def coedges(self, loop):
        out, first = [], loop.ptr(5)
        c = first
        while c is not None and c >= 0:
            out.append(self.r[c])
            c = self.r[c].ptr(4)
            if c == first or len(out) > 100000:
                break
        return out

    def edge_of(self, coedge):
        return self.r[coedge.ptr(7)]

    def partner_face(self, coedge):
        p = self.rec(coedge.ptr(6))
        if not p:
            return None
        return self.r[p.ptr(9)].ptr(6)     # partner coedge -> loop -> face

    def vertex_pos(self, v):
        return self.r[self.r[v].ptr(5)].nums(4, 3)

    def edge_curve(self, edge):
        c = self.rec(edge.ptr(9))
        return c.base if c else None


# ---------------------------------------------------------------- B-splines

def _subtypes(model):
    """Index every subtype object '{ name ...' in file order (ACIS numbers them
    for '{ ref n }' back-references)."""
    if getattr(model, "_sub", None) is None:
        table = []
        for rec in model.r:
            f = rec.f
            for i, t in enumerate(f):
                if t == "{" and i + 1 < len(f) and f[i + 1] != "ref":
                    table.append((rec.index, i + 1))
        model._sub = table
    return model._sub


def _bspline_at(model, rec, i):
    """Parse '<name> <ver?> full nubs|nurbs <deg> open|closed|periodic <n> knots... pts...'
    starting at field i (the subtype name). Returns (deg, knots, ctrl, weights)."""
    f = rec.f
    if f[i] == "ref":
        ri, rj = _subtypes(model)[int(f[i + 1])]
        return _bspline_at(model, model.r[ri], rj)
    j = i + 1
    while j < len(f) and f[j] not in ("nubs", "nurbs", "nullbs"):
        j += 1
    if j >= len(f) or f[j] == "nullbs":
        return None
    rational = f[j] == "nurbs"
    deg = int(f[j + 1])
    nk = int(f[j + 3])
    j += 4
    knots = []
    for _ in range(nk):
        knots += [float(f[j])] * int(f[j + 1])
        j += 2
    n = len(knots) - deg + 1
    ctrl, w = [], []
    for _ in range(n):
        ctrl.append([float(f[j]), float(f[j + 1]), float(f[j + 2])])
        if rational:
            w.append(float(f[j + 3]))
            j += 4
        else:
            w.append(1.0)
            j += 3
    # ACIS stores knots without the end duplicates: pad to clamped form
    knots = [knots[0]] + knots + [knots[-1]]
    return deg, knots, ctrl, w


def _deboor(deg, knots, ctrl, w, t):
    k = deg
    while k + 1 < len(knots) - deg - 1 and knots[k + 1] <= t:
        k += 1
    d = [[c[0] * wi, c[1] * wi, c[2] * wi, wi] for c, wi in zip(ctrl[k - deg:k + 1], w[k - deg:k + 1])]
    for r in range(1, deg + 1):
        for jj in range(deg, r - 1, -1):
            lo, hi = knots[jj + k - deg], knots[jj + 1 + k - r]
            a = 0.0 if hi == lo else (t - lo) / (hi - lo)
            d[jj] = [(1 - a) * d[jj - 1][q] + a * d[jj][q] for q in range(4)]
    return [d[deg][0] / d[deg][3], d[deg][1] / d[deg][3], d[deg][2] / d[deg][3]]


def intcurve_points(model, crv, samples=64):
    f = crv.f
    if "{" not in f:
        return None
    try:
        bs = _bspline_at(model, crv, f.index("{") + 1)
    except (ValueError, IndexError):
        return None
    if not bs:
        return None
    deg, knots, ctrl, w = bs
    t0, t1 = knots[deg], knots[-deg - 1]
    return [_deboor(deg, knots, ctrl, w, t0 + (t1 - t0) * i / samples) for i in range(samples + 1)]
