"""Inspect SAT boundary partners, distinguishing confirmed degenerate cone poles.

This is a boundary check, not a self-intersection or full solid-validity proof.
The record offsets apply to this repository's CST ACIS 31 SAT representation.
"""
import math


def cone_pole(model, face, coedge, tolerance):
    edge = model.edge_of(coedge)
    # ACIS edge: start vertex/parameter at 4/5; end vertex/parameter at 6/7;
    # first coedge at 8; curve at 9. A closed circle also shares endpoints,
    # so null geometry and a collapsed box are both required.
    start, end = edge.ptr(4), edge.ptr(6)
    if start is None or start < 0 or start != end or model.rec(edge.ptr(9)) is not None:
        return False
    try:
        at = edge.f.index('T')
        box = edge.nums(at + 1, 6)
        if any(not math.isfinite(v) for v in box):
            return False
        if max(abs(box[i + 3] - box[i]) for i in range(3)) > tolerance:
            return False
        point = [(box[i] + box[i + 3]) / 2 for i in range(3)]
        surface = model.surface(face)
        if surface['kind'] != 'cone' or abs(surface['sine']) < 1e-12 or abs(surface['cosine']) < 1e-12:
            return False
        slope = surface['sine'] / surface['cosine']
        apex = [p - u * surface['radius'] / slope for p, u in zip(surface['point'], surface['axis'])]
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(point, apex))) <= tolerance
    except (IndexError, KeyError, TypeError, ValueError):
        return False


def boundary_report(model, tolerance=1e-7):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Boundary tolerance must be positive and finite')
    paired, poles, unresolved = 0, [], []
    for face in model.faces:
        for loop in model.loops(face):
            for coedge in model.coedges(loop):
                if model.rec(coedge.ptr(6)) is not None:
                    paired += 1
                elif cone_pole(model, face, coedge, tolerance):
                    poles.append({'face_record': face.index, 'coedge_record': coedge.index})
                else:
                    unresolved.append({'face_record': face.index, 'coedge_record': coedge.index})
    return {'paired_coedges': paired, 'confirmed_degenerate_cone_poles': poles,
            'unresolved_unpaired_coedges': unresolved, 'boundary_check_passed': not unresolved,
            'tolerance_model_units': tolerance}
