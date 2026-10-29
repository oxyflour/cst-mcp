#!/usr/bin/env python3
"""cstmcp -- orchestrate the cst-mcp server and its private CST stacks.

Everything that used to be PowerShell lives here: process discovery, DLL
injection, owner lifecycle, isolated stacks. Standard library only (ctypes for
Win32), so it runs on any Python 3.8+ on this machine.

Commands
    status                      what is running, which modelers carry an agent
    inject <pid> [--dll PATH]   inject the ACIS agent (no PowerShell)
    isolate                     new DE + its modeler + inject, print the stack
    up [options]                make sure an owner exists on a port
    down [options]              stop owner(s), optionally close their DE

Typical
    py -3.12 tools/cstmcp.py up --isolated
    py -3.12 tools/cstmcp.py status
    py -3.12 tools/cstmcp.py down --isolated
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, ".run")
CST_PY = r"C:\Programs\CST Studio Suite 2022\AMD64\python\python.exe"
DEFAULT_PORT = 8765
ISOLATED_PORTS = range(8770, 8800)

# ---------------------------------------------------------------- Win32 (ctypes)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.CreateRemoteThread.restype = wt.HANDLE

# Without explicit argtypes ctypes passes Python ints as 32-bit C ints and
# Python str as narrow strings, which truncates 64-bit pointers and makes
# GetModuleHandleW return NULL -> the remote thread jumps to address 0.
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
k32.GetModuleHandleW.restype = wt.HMODULE
k32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]
k32.GetProcAddress.restype = ctypes.c_void_p
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                   ctypes.POINTER(wt.DWORD)]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.GetExitCodeThread.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
k32.LoadLibraryW.restype = wt.HMODULE
k32.FreeLibrary.argtypes = [wt.HMODULE]
k32.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def processes():
    """[(pid, parent_pid, exe)] via Toolhelp32."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    out = []
    try:
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return out


def modules(pid):
    """Loaded module names for a pid, [] when it cannot be opened."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == INVALID_HANDLE_VALUE:
        return []
    entry = MODULEENTRY32W()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
    names = []
    try:
        if k32.Module32FirstW(snap, ctypes.byref(entry)):
            while True:
                names.append(entry.szModule)
                if not k32.Module32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return names


def inject(pid, dll):
    """Classic CreateRemoteThread(LoadLibraryW). Raises on failure."""
    if not os.path.isfile(dll):
        raise SystemExit("DLL not found: %s" % dll)
    path = os.path.abspath(dll)
    access = PROCESS_ALL_ACCESS
    h = k32.OpenProcess(access, False, pid)
    if not h:
        raise SystemExit("OpenProcess(%d) failed: %d" % (pid, ctypes.get_last_error()))
    try:
        data = (path + "\0").encode("utf-16-le")
        size = len(data)
        remote = k32.VirtualAllocEx(h, None, size, MEM_COMMIT_RESERVE, PAGE_READWRITE)
        if not remote:
            raise SystemExit("VirtualAllocEx failed: %d" % ctypes.get_last_error())
        written = ctypes.c_size_t(0)
        if not k32.WriteProcessMemory(h, ctypes.c_void_p(remote), data, size, ctypes.byref(written)):
            raise SystemExit("WriteProcessMemory failed: %d" % ctypes.get_last_error())
        load_library = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        if not load_library:
            raise SystemExit("GetProcAddress(LoadLibraryW) returned NULL: %d" % ctypes.get_last_error())
        tid = wt.DWORD(0)
        th = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(load_library), ctypes.c_void_p(remote), 0, ctypes.byref(tid))
        if not th:
            raise SystemExit("CreateRemoteThread failed: %d" % ctypes.get_last_error())
        k32.WaitForSingleObject(th, 15000)
        code = wt.DWORD(0)
        k32.GetExitCodeThread(th, ctypes.byref(code))
        k32.CloseHandle(th)
        k32.VirtualFreeEx(h, ctypes.c_void_p(remote), 0, MEM_RELEASE)
        if code.value == 0:
            raise SystemExit("LoadLibraryW returned NULL in the target (bitness or dependency problem)")
        return code.value
    finally:
        k32.CloseHandle(h)


def kill(pid):
    h = k32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(k32.TerminateProcess(h, 1))
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------------- helpers

def newest_agent():
    native = os.path.join(ROOT, "native")
    if not os.path.isdir(native):
        return None
    best = None
    for name in os.listdir(native):
        if not name.lower().startswith("cst_acis_agent") or not name.lower().endswith(".dll"):
            continue
        stem = name[len("cst_acis_agent"):-len(".dll")]
        if not stem.isdigit():
            continue
        if best is None or int(stem) > best[0]:
            best = (int(stem), os.path.join(native, name))
    return best[1] if best else None


def http_json(url, payload=None, timeout=3):
    data = None
    headers = {"accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode() or "null")


def health(port, timeout=1.5):
    try:
        h = http_json("http://127.0.0.1:%d/health" % port, timeout=timeout)
        return h if h and h.get("app") == "cst-mcp" else None
    except Exception:
        return None


def free_port():
    for p in ISOLATED_PORTS:
        if health(p) is None and not port_listening(p):
            return p
    raise SystemExit("no free port in %d-%d" % (ISOLATED_PORTS[0], ISOLATED_PORTS[-1]))


def port_listening(port):
    """Cheap TCP probe; True when something accepts a connection."""
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def node_exe():
    for cand in (shutil.which("node"), r"C:\Program Files\nodejs\node.exe"):
        if cand and os.path.isfile(cand):
            return cand
    raise SystemExit("node not found in PATH")


def wait_health(port, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = health(port)
        if h:
            return h
        time.sleep(0.3)
    return None



def wait_agent_pipe(pid, timeout=10):
    """True when the agent answers ping on its named pipe."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(r"\\.\pipe\cst-acis-%d" % pid, "r+b", buffering=0) as fh:
                fh.write(b"ping\n")
                reply = fh.readline().decode(errors="replace").strip()
                if reply.startswith("OK"):
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False

def cmd_symbols(args):
    """Resolve every mangled name declared in native/*.h against SpaACIS.dll."""
    import glob
    import re

    dll = args.spaacis
    if not os.path.isfile(dll):
        raise SystemExit("SpaACIS.dll not found: %s" % dll)

    syms = {}
    for header in glob.glob(os.path.join(ROOT, "native", "*.h")):
        with open(header, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r'#define\s+(\w+)\s+"(\?.+?)"', line)
                if m:
                    syms[m.group(1)] = m.group(2)
    if not syms:
        raise SystemExit("no symbol constants found in native/*.h")

    h = k32.LoadLibraryW(os.path.abspath(dll))
    if not h:
        raise SystemExit("LoadLibrary(%s) failed: %d" % (dll, ctypes.get_last_error()))
    missing = []
    try:
        for name in sorted(syms):
            if not k32.GetProcAddress(h, syms[name].encode()):
                missing.append(name)
                print("MISS %-28s %s" % (name, syms[name]))
    finally:
        k32.FreeLibrary(h)

    print("%d symbols, %d missing" % (len(syms), len(missing)))
    return 1 if missing else 0
# ------------------------------------------------------------------- commands

def cmd_status(args):
    print("owner(s):")
    found = False
    for port in [DEFAULT_PORT] + list(ISOLATED_PORTS):
        h = health(port)
        if h:
            found = True
            state = os.path.join(RUN, "owner-%d.json" % port)
            extra = ""
            if os.path.isfile(state):
                extra = json.load(open(state))
                extra = " de=%s modeler=%s" % (extra.get("dePid"), extra.get("modelerPid"))
            print("  :%d pid=%s%s" % (port, h.get("pid"), extra))
    if not found:
        print("  none")

    procs = processes()
    des = [p for p in procs if p[2].lower().startswith("cst design environment")]
    mods = [p for p in procs if p[2].lower() == "modeler_amd64.exe"]
    print("design environments:")
    for pid, ppid, exe in des:
        print("  pid=%d %s" % (pid, exe))
    print("modelers:")
    for pid, ppid, exe in mods:
        agents = [m for m in modules(pid) if m.lower().startswith("cst_acis_agent")]
        print("  pid=%d parent=%d agent=%s" % (pid, ppid, ",".join(agents) or "-"))
    return 0


def cmd_inject(args):
    dll = args.dll or newest_agent()
    if not dll:
        raise SystemExit("no built agent dll; compile native/ first")
    base = inject(args.pid, dll)
    print(json.dumps({"pid": args.pid, "dll": os.path.basename(dll), "base": hex(base)}))
    return 0


def cmd_isolate(args):
    if not os.path.isfile(CST_PY):
        raise SystemExit("CST python not found: %s" % CST_PY)
    helper = os.path.join(ROOT, "scripts", "new_isolated_de.py")
    raw = subprocess.run([CST_PY, helper], capture_output=True, text=True, timeout=300)
    line = next((l for l in raw.stdout.splitlines() if l.strip().startswith("{")), None)
    if not line:
        raise SystemExit("could not start a DE:\n%s\n%s" % (raw.stdout, raw.stderr))
    info = json.loads(line)

    deadline = time.time() + args.timeout
    modeler = None
    while time.time() < deadline and modeler is None:
        for pid, ppid, exe in processes():
            if exe.lower() == "modeler_amd64.exe" and ppid == info["de_pid"]:
                modeler = pid
                break
        if modeler is None:
            time.sleep(0.5)
    if modeler is None:
        raise SystemExit("DE %d never spawned a modeler" % info["de_pid"])

    # Injecting a brand-new modeler crashes it: CreateRemoteThread(LoadLibraryW)
    # lands while the loader lock is still held. Wait until it is past startup
    # (SpaACIS imported and a couple of seconds of runtime) before touching it.
    dll = newest_agent()
    if not dll:
        raise SystemExit("no built agent dll; compile native/ first")

    started = None
    for pid, ppid, exe in processes():
        if pid == modeler:
            started = time.time()
            break
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        procs = {p[0]: p for p in processes()}
        if modeler not in procs:
            raise SystemExit("modeler %d exited before injection" % modeler)
        mods = [m.lower() for m in modules(modeler)]
        ready = "spaacis.dll" in mods and "acisinterface_amd64.dll" in mods
        if ready:
            time.sleep(args.settle)
            if modeler not in {p[0] for p in processes()}:
                raise SystemExit("modeler %d exited during settle" % modeler)
            break
        time.sleep(0.4)
    else:
        raise SystemExit("modeler %d never finished starting" % modeler)

    inject(modeler, dll)

    # Verify by talking to the pipe: the module list can lag or the snapshot can
    # fail, but a live pipe server is definitive.
    if not wait_agent_pipe(modeler, timeout=15):
        loaded = [m for m in modules(modeler) if m.lower().startswith("cst_acis_agent")]
        raise SystemExit("agent not answering on %d (modules=%s)" % (modeler, loaded))

    stack = {
        "dePid": info["de_pid"],
        "modelerPid": modeler,
        "agent": os.path.basename(dll),
        "project": info.get("project"),
    }
    print(json.dumps(stack))
    return 0


def cmd_up(args):
    port = args.port
    stack = None
    if args.de_pid and args.modeler_pid:
        # reuse a stack that already exists (no new licence, no new CST start)
        stack = {"dePid": args.de_pid, "modelerPid": args.modeler_pid, "agent": "(existing)"}
    if args.isolated:
        raw = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "isolate"],
            capture_output=True, text=True, timeout=400,
        )
        line = next((l for l in raw.stdout.splitlines() if l.strip().startswith("{")), None)
        if not line:
            raise SystemExit("isolate failed:\n%s\n%s" % (raw.stdout, raw.stderr))
        stack = json.loads(line)
        if port is None:
            port = free_port()
    if port is None:
        port = DEFAULT_PORT

    h = health(port)
    if h:
        print(json.dumps({"port": port, "pid": h["pid"], "reused": True, "stack": stack}))
        return 0

    os.makedirs(RUN, exist_ok=True)
    out = os.path.join(RUN, "server-%d.out.log" % port)
    err = os.path.join(RUN, "server-%d.err.log" % port)

    env = dict(os.environ)
    env["CST_MCP_PORT"] = str(port)
    env.pop("CST_MCP_TRANSPORT", None)
    if stack:
        env["CST_MCP_DE_PID"] = str(stack["dePid"])
        env["CST_MCP_MODELER_PID"] = str(stack["modelerPid"])
    if args.token:
        env["CST_MCP_TOKEN"] = args.token

    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(out, "ab") as fo, open(err, "ab") as fe:
        proc = subprocess.Popen(
            [node_exe(), "src/server.mjs"],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=fo, stderr=fe, creationflags=flags,
        )

    h = wait_health(port)
    if not h:
        tail = ""
        if os.path.isfile(err):
            tail = "".join(open(err, errors="replace").readlines()[-15:])
        raise SystemExit("owner did not come up on %d (pid %d)\n%s" % (port, proc.pid, tail))

    state = {"pid": h["pid"], "port": port, "url": "http://127.0.0.1:%d/mcp" % port}
    if stack:
        state.update(stack)
    with open(os.path.join(RUN, "owner-%d.json" % port), "w") as fh:
        json.dump(state, fh, indent=2)
    print(json.dumps(state, indent=2))
    return 0


def cmd_down(args):
    ports = [args.port] if args.port else [DEFAULT_PORT] + list(ISOLATED_PORTS)
    stopped = 0
    for port in ports:
        h = health(port)
        if not h:
            continue
        state_path = os.path.join(RUN, "owner-%d.json" % port)
        state = json.load(open(state_path)) if os.path.isfile(state_path) else {}
        if kill(int(h["pid"])):
            stopped += 1
            print("stopped owner on :%d (pid %s)" % (port, h["pid"]))
        if args.with_cst and state.get("dePid"):
            close_de(state["dePid"])
        if os.path.isfile(state_path):
            os.remove(state_path)
    if not stopped:
        print("no owner was running")
    return 0


def close_de(de_pid):
    code = (
        "import cst.interface as ci\n"
        "de = ci.DesignEnvironment.connect(%d)\n"
        "de.set_quiet_mode(True)\n"
        "de.close()\n" % int(de_pid)
    )
    try:
        subprocess.run([CST_PY, "-c", code], capture_output=True, timeout=120)
        print("closed DE %d" % de_pid)
    except Exception as exc:  # pragma: no cover - best effort
        print("could not close DE %d: %s" % (de_pid, exc))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cstmcp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show owners, DEs, modelers and agents")

    p = sub.add_parser("symbols", help="check that every ACIS symbol constant resolves")
    p.add_argument("--spaacis", default=r"C:\Programs\CST Studio Suite 2022\ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll")

    p = sub.add_parser("inject", help="inject the ACIS agent into a modeler")
    p.add_argument("pid", type=int)
    p.add_argument("--dll")

    p = sub.add_parser("isolate", help="create a private DE+modeler and inject")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--settle", type=float, default=3.0, help="seconds to wait after the modeler is up")

    p = sub.add_parser("up", help="start (or reuse) an owner")
    p.add_argument("--port", type=int)
    p.add_argument("--isolated", action="store_true", help="create a private DE+modeler first")
    p.add_argument("--de-pid", type=int, default=0, help="pin to an existing DE")
    p.add_argument("--modeler-pid", type=int, default=0, help="pin to that DE's modeler")
    p.add_argument("--token")

    p = sub.add_parser("down", help="stop owner(s)")
    p.add_argument("--port", type=int)
    p.add_argument("--with-cst", action="store_true", help="also close the isolated DE")
    p.add_argument("--isolated", action="store_true", help="alias kept for symmetry")

    args = ap.parse_args(argv)
    return {"status": cmd_status, "symbols": cmd_symbols, "inject": cmd_inject, "isolate": cmd_isolate,
            "up": cmd_up, "down": cmd_down}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
