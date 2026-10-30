"""Classify faces of a SAT body relative to a machining axis (Z) and build
their plan-view (XY) regions."""
import math

from shapely.geometry import Polygon
from shapely.validation import make_valid

import draw
import sat

ANG = 1e-6


def outward_normal(m, face, s):
    sign = -1.0 if s["reversed"] else 1.0
    return [sign * c for c in s["normal"]]


def loop_points(m, loop):
    pts = []
    for ce in m.coedges(loop):
        e = m.edge_of(ce)
        p = draw.edge_points(m, e)
        if ce.f[8] == "reversed":
            p = p[::-1]
        pts.extend(p[:-1])
    return pts


def region(m, face):
    """XY region of a face as even-odd combination of its projected loops."""
    reg = None
    for lp in m.loops(face):
        pts = [(p[0], p[1]) for p in loop_points(m, lp)]
        if len(pts) < 3:
            continue
        poly = make_valid(Polygon(pts))
        reg = poly if reg is None else reg.symmetric_difference(poly)
    return reg


def classify(m, face):
    s = m.surface(face)
    k = s["kind"]
    if k == "plane":
        n = outward_normal(m, face, s)
        if abs(n[2]) > 1 - ANG:
            return ("up" if n[2] > 0 else "down"), s["point"][2], s
        if abs(n[2]) < ANG:
            return "wall", None, s
        return "slope", None, s
    if k == "cone" and s["cylinder"]:
        if abs(abs(s["axis"][2]) - 1) < ANG:
            return "wall", None, s
        return "fillet_cyl", None, s
    if k == "cone":
        return ("draft" if abs(abs(s["axis"][2]) - 1) < ANG else "cone"), None, s
    if k in ("torus", "sphere"):
        return "fillet_" + k, None, s
    return "spline", None, s
