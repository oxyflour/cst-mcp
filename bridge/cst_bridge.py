"""CST Studio Suite adapter process.

Runs on CST's *bundled* Python 3.6 (``AMD64\\python\\python.exe``) because
``_cst_interface.pyd`` ships as cp36..cp39 builds only.

Protocol: newline-delimited JSON over stdin/stdout, one request/response pair at
a time (the Node side serialises calls, CST itself is single-session anyway).

    --> {"id": "1", "method": "vba.run", "params": {"code": "..."}}
    <-- {"id": "1", "ok": true, "result": {...}}
    <-- {"id": "1", "ok": false, "error": {"type": "...", "message": "..."}}

stdout carries protocol traffic only; all diagnostics go to stderr.
"""

from __future__ import print_function

import json
import sys
import traceback

import cst.interface as ci
import cst.results as cr

STATE = {
    "de": None,      # DesignEnvironment handle
}


def de_require():
    de = STATE["de"]
    if de is None or not de.is_connected():
        raise RuntimeError("not connected to a Design Environment; call de.connect first")
    return de


# --------------------------------------------------------------------------- #
# methods
# --------------------------------------------------------------------------- #

def m_ping(params):
    return {"pong": True, "python": sys.version.split()[0]}


def m_de_list(params):
    pids = ci.running_design_environments()
    return {"pids": pids, "connected_pid": STATE["de"].pid() if STATE["de"] else None}


def m_de_connect(params):
    mode = params.get("mode", "any")
    pid = int(params.get("pid", -1))

    if STATE["de"] is not None:
        try:
            if STATE["de"].is_connected():
                STATE["de"].close()
        except Exception:
            pass
        STATE["de"] = None

    if mode == "any":
        de = ci.DesignEnvironment.connect_to_any()
    elif mode == "pid":
        de = ci.DesignEnvironment.connect(pid)
    elif mode == "new":
        de = ci.DesignEnvironment.new(options=params.get("options"))
    elif mode == "any_or_new":
        de = ci.DesignEnvironment.connect_to_any_or_new()
    else:
        raise ValueError("unknown mode: %r" % (mode,))

    try:
        de.set_quiet_mode(True)   # documented as step one: modal dialogs would hang every later call
    except Exception:
        pass
    STATE["de"] = de
    return {"pid": de.pid(), "version": ci.DesignEnvironment.version()}


def m_de_status(params):
    de = STATE["de"]
    if de is None or not de.is_connected():
        return {"connected": False, "running": ci.running_design_environments()}
    out = {
        "connected": True,
        "pid": de.pid(),
        "has_active_project": de.has_active_project(),
        "open_projects": de.list_open_projects(),
        "quiet": de.in_quiet_mode(),
    }
    if de.has_active_project():
        prj = de.active_project()
        out["active_project"] = {"file": _safe(prj.filename), "folder": _safe(prj.folder)}
    return out


def m_project_open(params):
    de = de_require()
    prj = de.open_project(params["path"])
    return {"file": _safe(prj.filename)}


def m_project_activate(params):
    de = de_require()
    prj = de.get_open_project(params["path"])
    prj.activate()
    return {"file": _safe(prj.filename)}


def m_vba_run(params):
    """Execute a VBA snippet inside the active project's history list."""
    de = de_require()
    prj = de.active_project()
    code = params["code"]
    header = params.get("header", "mcp")
    timeout = params.get("timeout")

    modeler = prj.modeler
    if modeler is not None:
        # CST's wrapper rejects an explicit None timeout.
        if timeout is None:
            modeler.add_to_history(header, code)
        else:
            modeler.add_to_history(header, code, timeout)
        return {"applied_to": "modeler"}

    schematic = getattr(prj, "schematic", None)
    if schematic is not None:
        schematic.execute_vba_code(code, timeout)
        return {"applied_to": "schematic"}

    raise RuntimeError("active project has neither a modeler nor a schematic")


def m_history_rebuild(params):
    de = de_require()
    prj = de.active_project()
    prj.modeler.full_history_rebuild(params.get("timeout"))
    return {"rebuilt": True}


def m_solver_start(params):
    de = de_require()
    prj = de.active_project()
    prj.modeler.start_solver(params.get("timeout"))
    return {"started": True}


def m_solver_run_blocking(params):
    de = de_require()
    prj = de.active_project()
    ok = prj.modeler.run_solver(params.get("timeout"))
    return {"ok": bool(ok)}


def m_solver_state(params):
    de = de_require()
    prj = de.active_project()
    modeler = prj.modeler
    running = bool(modeler.is_solver_running())
    name = None
    if running:
        try:
            name = modeler.get_active_solver_name()
        except Exception:
            name = None
    return {"running": running, "solver": name}


def m_solver_abort(params):
    de = de_require()
    de.active_project().modeler.abort_solver(params.get("timeout"))
    return {"aborted": True}


def m_results_tree(params):
    """Read 0D/1D results straight from disk; no DE and no licence needed."""
    pf = cr.ProjectFile(params["path"], allow_interactive=params.get("interactive", False))
    model = pf.get_3d() if pf.get_3d() is not None else pf.get_schematic()
    return {"tree": _tree(model.get_result_tree())}


def m_shutdown(params):
    STATE["de"] = None
    return {"bye": True}


METHODS = {
    "ping": m_ping,
    "de.list": m_de_list,
    "de.connect": m_de_connect,
    "de.status": m_de_status,
    "project.open": m_project_open,
    "project.activate": m_project_activate,
    "vba.run": m_vba_run,
    "history.rebuild": m_history_rebuild,
    "solver.start": m_solver_start,
    "solver.run": m_solver_run_blocking,
    "solver.state": m_solver_state,
    "solver.abort": m_solver_abort,
    "results.tree": m_results_tree,
    "shutdown": m_shutdown,
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return {"error": str(exc)}


def _tree(node, depth=0):
    if depth > 2:
        return "..."
    out = {}
    for name in node.keys():
        child = node[name]
        out[name] = _tree(child, depth + 1) if hasattr(child, "keys") else str(child)
    return out


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main():
    _send({"id": None, "ok": True, "result": {"ready": True, "python": sys.version.split()[0]}})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            fn = METHODS.get(req.get("method"))
            if fn is None:
                raise ValueError("unknown method: %r" % (req.get("method"),))
            result = fn(req.get("params") or {})
            _send({"id": req_id, "ok": True, "result": result})
        except Exception as exc:  # noqa: BLE001 - one failed call must not kill the bridge
            traceback.print_exc(file=sys.stderr)
            _send({
                "id": req_id,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })


if __name__ == "__main__":
    main()
