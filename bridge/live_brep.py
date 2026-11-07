"""Read-only solid enumeration, with query results returned over an in-memory pipe.

Python 3.6 / standard library only. The native agent captures BRep during each
IsPointInsideShape call. No geometry is serialized to an interchange file.
"""
import ctypes
from ctypes import wintypes as wt
import threading
import uuid


def _hex_string(value):
    return bytes.fromhex(value).decode("utf-16-be")


def execute_control_macro(project, code):
    """Run an internal read-only control macro; receive its ASCII line protocol in memory."""
    schematic = project.schematic
    if schematic is None:
        raise RuntimeError("this project has no control-macro interface")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD,
                                  wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    k.CreateNamedPipeW.restype = wt.HANDLE
    k.ConnectNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.GetCurrentThreadId.restype = wt.DWORD
    k.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.OpenThread.restype = wt.HANDLE
    k.CancelSynchronousIo.argtypes = [wt.HANDLE]
    pipe_name = "\\\\.\\pipe\\cst-brep-" + uuid.uuid4().hex
    handle = k.CreateNamedPipeW(pipe_name, 1, 0, 1, 65536, 65536, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    started = threading.Event()
    receiver_id = []
    chunks, errors = [], []

    def receive():
        try:
            receiver_id.append(k.GetCurrentThreadId())
            started.set()
            if not k.ConnectNamedPipe(handle, None) and ctypes.get_last_error() not in (535, 232):
                raise ctypes.WinError(ctypes.get_last_error())
            size = 0
            tail = b""
            while True:
                buf = ctypes.create_string_buffer(65536)
                count = wt.DWORD()
                if k.ReadFile(handle, buf, len(buf), ctypes.byref(count), None):
                    chunks.append(buf.raw[:count.value])
                    size += count.value
                    if size > 16 * 1024 * 1024:
                        raise RuntimeError("control macro response exceeds 16 MiB")
                    tail = (tail + buf.raw[:count.value]).replace(b"\r", b"")[-8:]
                    if tail.endswith(b"END\n"):
                        break
                    continue
                error = ctypes.get_last_error()
                if error in (109, 232):
                    break
                raise ctypes.WinError(error)
        except Exception as exc:
            errors.append(exc)
        finally:
            k.CloseHandle(handle)

    thread = threading.Thread(target=receive)
    thread.daemon = True
    thread.start()
    started.wait(1)
    code = code.replace('Open "PIPE_NAME" For Output As #fh',
                        'Open "' + pipe_name + '" For Output As #fh', 1)
    try:
        schematic.execute_vba_code(code)
        thread.join(3)
        if thread.is_alive():
            raise RuntimeError("CST did not finish its query (macro failed or timed out)")
        if errors:
            raise errors[0]
    finally:
        if thread.is_alive() and receiver_id:
            thread_handle = k.OpenThread(1, False, receiver_id[0])
            if thread_handle:
                k.CancelSynchronousIo(thread_handle)
                k.CloseHandle(thread_handle)
        thread.join(1)
    lines = b"".join(chunks).decode("ascii").replace("\r", "").splitlines()
    if not lines or not lines[0].startswith("BEGIN\t") or lines[-1] != "END":
        raise RuntimeError("CST returned an incomplete query response")
    return lines


def enumerate_solids(project, names=None, offset=0, limit=None):
    if names is not None and (not isinstance(names, list) or len(names) > 20 or
                              any(not isinstance(name, str) or len(name) > 4096 for name in names)):
        raise ValueError("names must contain at most 20 solid names")
    if not isinstance(offset, int) or offset < 0 or (limit is not None and
            (not isinstance(limit, int) or limit < 1 or limit > 200)):
        raise ValueError("invalid solid page")
    if names is not None:
        def literal(value):
            return '"' + value.replace('"', '""').replace("\r", '" & Chr(13) & "').replace("\n", '" & Chr(10) & "') + '"'
        selected = " Or ".join("nm = " + literal(name) for name in names) or "False"
    else:
        selected = "i >= %d" % offset
        if limit is not None:
            selected += " And i < %d" % (offset + limit)
    code = '''Function BrepHex(ByVal value As String) As String
    Dim j As Long, encoded As String
    For j = 1 To Len(value)
        encoded = encoded & Right$("0000" & Hex(AscW(Mid$(value, j, 1))), 4)
    Next j
    BrepHex = encoded
End Function

Sub Main
    Dim fh As Integer, i As Long, total As Long, nm As String, mat As String
    Dim xmin As Double, xmax As Double, ymin As Double, ymax As Double, zmin As Double, zmax As Double
    Dim valid As Boolean, inside As Boolean
    fh = FreeFile
    Open "PIPE_NAME" For Output As #fh
    total = Solid.GetNumberOfShapes
    Print #fh, "BEGIN" & vbTab & CStr(total)
    For i = 0 To total - 1
        nm = Solid.GetNameOfShapeFromIndex(i)
        If SELECTED Then
        mat = Solid.GetMaterialNameForShape(nm)
        valid = Solid.GetLooseBoundingBoxOfShape(nm, xmin, xmax, ymin, ymax, zmin, zmax)
        If valid Then
            inside = Solid.IsPointInsideShape((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2, nm)
            Print #fh, "SOLID" & vbTab & CStr(i) & vbTab & BrepHex(nm) & vbTab & BrepHex(mat)
        Else
            Print #fh, "ERROR" & vbTab & BrepHex(nm)
        End If
        End If
    Next i
    Print #fh, "END"
    Close #fh
End Sub
'''.replace("SELECTED", selected)
    lines = execute_control_macro(project, code)
    total = int(lines[0].split("\t")[1])
    solids = []
    for line in lines[1:-1]:
        fields = line.split("\t")
        if fields[0] == "ERROR":
            raise RuntimeError("cannot query solid: " + _hex_string(fields[1]))
        if (len(fields) != 4 or fields[0] != "SOLID" or int(fields[1]) < 0 or
                int(fields[1]) >= total or (solids and int(fields[1]) <= solids[-1]["index"])):
            raise RuntimeError("invalid solid enumeration order")
        solids.append({"index": int(fields[1]), "name": _hex_string(fields[2]), "material": _hex_string(fields[3])})
    if names is None and len(solids) != (max(0, total-offset) if limit is None else max(0, min(limit, total-offset))):
        raise RuntimeError("CST solid enumeration was incomplete")
    if names is not None and any(solid["name"] not in names for solid in solids):
        raise RuntimeError("CST returned an unexpected solid")
    return {"file": project.filename(), "total": total, "solids": solids}
