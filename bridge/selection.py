"""CST selection/pick queries, using only documented read-only VBA APIs."""
import math

from live_brep import execute_control_macro, _hex_string


_MACRO = '''Function SelectionHex(ByVal value As String) As String
    Dim j As Long, encoded As String
    For j = 1 To Len(value)
        encoded = encoded & Right$("0000" & Hex(AscW(Mid$(value, j, 1))), 4)
    Next j
    SelectionHex = encoded
End Function

Sub Main
    Dim fh As Integer, i As Long, ordinal As Long
    Dim nt As Long, nf As Long, ne As Long, np As Long
    Dim path As String, nm As String, mat As String
    Dim faceId As Long, edgeId As Long, vertexId As Long
    Dim x As Double, y As Double, z As Double, area As Double
    Dim valid As Boolean
    fh = FreeFile
    Open "PIPE_NAME" For Output As #fh
    nt = GetNumberOfSelectedTreeItems
    nf = Pick.GetNumberOfPickedFaces
    ne = Pick.GetNumberOfPickedEdges
    np = Pick.GetNumberOfPickedPoints
    Print #fh, "BEGIN" & vbTab & CStr(nt) & vbTab & CStr(nf) & vbTab & CStr(ne) & vbTab & CStr(np)
    ordinal = 0
    If nt > 0 Then
        path = GetSelectedTreeItem
        For i = 0 To nt - 1
            If ordinal >= PAGE_START And ordinal < PAGE_END Then
                nm = ""
                mat = ""
                On Error Resume Next
                nm = GetGlobalNameFromTreeName(path)
                On Error GoTo 0
                If Left$(nm, 6) = "solid$" Then
                    nm = Mid$(nm, 7)
                Else
                    nm = ""
                End If
                If nm <> "" Then
                    If Solid.DoesExist(nm) Then
                        mat = Solid.GetMaterialNameForShape(nm)
                    Else
                        nm = ""
                    End If
                End If
                Print #fh, "TREE" & vbTab & CStr(ordinal) & vbTab & SelectionHex(path) & vbTab & SelectionHex(nm) & vbTab & SelectionHex(mat)
            End If
            ordinal = ordinal + 1
            If i + 1 < nt Then path = GetNextSelectedTreeItem
        Next i
    End If
    For i = 0 To nf - 1
        If ordinal >= PAGE_START And ordinal < PAGE_END Then
            nm = Pick.GetPickedFaceByIndex(i, faceId)
            area = Pick.GetPickedFaceAreaByIndex(i)
            Print #fh, "FACE" & vbTab & CStr(ordinal) & vbTab & SelectionHex(nm) & vbTab & CStr(faceId) & vbTab & Trim$(Str$(area))
        End If
        ordinal = ordinal + 1
    Next i
    For i = 0 To ne - 1
        If ordinal >= PAGE_START And ordinal < PAGE_END Then
            nm = Pick.GetPickedEdgeByIndex(i, edgeId, vertexId)
            Print #fh, "EDGE" & vbTab & CStr(ordinal) & vbTab & SelectionHex(nm) & vbTab & CStr(edgeId) & vbTab & CStr(vertexId)
        End If
        ordinal = ordinal + 1
    Next i
    For i = 0 To np - 1
        If ordinal >= PAGE_START And ordinal < PAGE_END Then
            valid = Pick.GetPickpointCoordinatesByIndex(i, x, y, z)
            If valid Then
                Print #fh, "POINT" & vbTab & CStr(ordinal) & vbTab & Trim$(Str$(x)) & vbTab & Trim$(Str$(y)) & vbTab & Trim$(Str$(z))
            Else
                Print #fh, "ERROR" & vbTab & CStr(ordinal)
            End If
        End If
        ordinal = ordinal + 1
    Next i
    Print #fh, "END"
    Close #fh
End Sub
'''


def parse_selection(lines, offset, limit):
    if not lines:
        raise RuntimeError("empty selection response")
    header = lines[0].split("\t")
    if len(header) != 5 or header[0] != "BEGIN" or lines[-1] != "END":
        raise RuntimeError("incomplete selection response")
    counts = dict(zip(("treeItems", "faces", "edges", "points"), map(int, header[1:])))
    if any(value < 0 for value in counts.values()):
        raise RuntimeError("invalid selection counts")
    nt, nf, ne, np = [counts[key] for key in ("treeItems", "faces", "edges", "points")]
    total = nt + nf + ne + np
    items = []
    for line in lines[1:-1]:
        fields = line.split("\t")
        if fields[0] == "ERROR":
            raise RuntimeError("selected point could not be read")
        if len(fields) != 5 or int(fields[1]) != offset + len(items):
            raise RuntimeError("invalid selection order")
        ordinal = int(fields[1])
        item = {"selectionIndex": ordinal}
        if fields[0] == "TREE" and ordinal < nt:
            name = _hex_string(fields[3])
            item.update(type="solid" if name else "tree_item", source="tree", treePath=_hex_string(fields[2]))
            if name:
                item.update(solidName=name, material=_hex_string(fields[4]))
        elif fields[0] in ("FACE", "EDGE"):
            name = _hex_string(fields[2])
            native_id = int(fields[3])
            if not name or native_id < 0:
                raise RuntimeError("picked entity has no valid solid/name ID")
            item.update(type=fields[0].lower(), source="pick", solidName=name)
            if fields[0] == "FACE" and nt <= ordinal < nt + nf:
                area = float(fields[4])
                if not math.isfinite(area) or area < 0:
                    raise RuntimeError("invalid picked face area")
                item.update(pickIndex=ordinal-nt, cstFaceId=native_id, area=area)
            elif fields[0] == "EDGE" and nt + nf <= ordinal < nt + nf + ne:
                vertex_id = int(fields[4])
                item.update(pickIndex=ordinal-nt-nf, cstEdgeId=native_id,
                            cstStartVertexId=vertex_id if vertex_id >= 0 else None)
            else:
                raise RuntimeError("picked entity type/count mismatch")
        elif fields[0] == "POINT" and nt + nf + ne <= ordinal < total:
            xyz = list(map(float, fields[2:]))
            if not all(math.isfinite(value) for value in xyz):
                raise RuntimeError("invalid picked point coordinates")
            item.update(type="point", source="pick", pickIndex=ordinal-nt-nf-ne,
                        position=xyz, coordinateFrame="global")
        else:
            raise RuntimeError("unexpected selection item")
        items.append(item)
    if len(items) != max(0, min(limit, total-offset)):
        raise RuntimeError("selection response was incomplete")
    return {"counts": counts, "total": total, "offset": offset, "limit": limit,
            "nextOffset": offset+limit if offset+limit < total else None, "items": items}


def read_selection(project, offset=0, limit=50):
    if (not isinstance(offset, int) or offset < 0 or not isinstance(limit, int)
            or limit < 1 or limit > 100):
        raise ValueError("invalid selection page")
    code = _MACRO.replace("PAGE_START", str(offset)).replace("PAGE_END", str(offset+limit))
    result = parse_selection(execute_control_macro(project, code), offset, limit)
    result["file"] = project.filename()
    return result
