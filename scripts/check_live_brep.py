"""End-to-end paged BRep API checks. --fixture modifies an empty disposable project.

  py -3.12 tools/cstmcp.py up --isolated
  py -3.12 scripts/check_live_brep.py --port 8770 --fixture

Without --fixture this only reads the active project. No SAT/STEP file is used.
--output saves a compact query report, never the complete model topology.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import urllib.request


REPLIES = []


def call(port, name, args=None, expect_error=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args or {}}}
    req = urllib.request.Request("http://127.0.0.1:%d/mcp" % port,
                                 json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    text = urllib.request.urlopen(req, timeout=180).read().decode()
    for line in text.splitlines():
        if line.startswith("data:"):
            text = line[5:]
    result = json.loads(text)
    if "result" in result:
        REPLIES.append({"tool": name, "bytes": len(result["result"]["content"][0]["text"].encode("utf-8"))})
        assert REPLIES[-1]["bytes"] <= 32768
    if expect_error:
        assert result["result"].get("isError"), result
        error = json.loads(result["result"]["content"][0]["text"])["error"]
        assert error["code"] == expect_error, error
        return error
    if "error" in result or result["result"].get("isError"):
        raise RuntimeError(result)
    return json.loads(result["result"]["content"][0]["text"])


def brick(name, x):
    return '\n'.join(['With Brick', '.Reset', '.Name "' + name + '"', '.Component "memory_test"',
                      '.Material "PEC"', '.Xrange "%s", "%s"' % (x, x+10),
                      '.Yrange "0", "10"', '.Zrange "0", "10"', '.Create', 'End With'])


def all_solids(port):
    items, offset = [], 0
    while offset is not None:
        result = call(port, "cst_list_solids", {"offset": offset, "limit": 2})
        items.extend(result["items"])
        offset = result["nextOffset"]
    return items


def check_queries(port, solid):
    solid_id = solid["id"]
    info = call(port, "cst_get_entity", {"id": solid_id})
    assert info["counts"] == solid["counts"] and info["type"] == "solid"
    faces = call(port, "cst_list_entities", {"solidId": solid_id, "type": "face", "limit": 200})
    assert faces["total"] == solid["counts"]["faces"]
    assert len(faces["ids"]) <= 200
    if not faces["ids"]:
        return {"solid": solid, "face": None}
    face_id = faces["ids"][0]
    face = call(port, "cst_get_entity", {"id": face_id})
    assert face["solidId"] == solid_id and face["type"] == "face"
    again = call(port, "cst_list_entities", {"solidId": solid_id, "type": "face", "limit": 1})
    assert again["ids"] == [face_id]
    loops = call(port, "cst_get_adjacency", {"id": face_id, "relation": "loops"})
    if not loops["ids"]:
        return {"solid": solid, "face": face}
    loop_id = loops["ids"][0]
    assert face["firstLoopId"] == loop_id
    first = call(port, "cst_get_loop_boundary", {"loopId": loop_id, "limit": 2})
    segments = first["items"][:]
    next_offset = first["nextOffset"]
    # Bound this smoke test even for faces with enormous boundary loops.
    while next_offset is not None and len(segments) < 50:
        following = call(port, "cst_get_loop_boundary", {"loopId": loop_id, "offset": next_offset, "limit": 50})
        segments.extend(following["items"])
        next_offset = following["nextOffset"]
    for i in range(len(segments) - 1):
        assert segments[i]["endVertexId"] == segments[i+1]["startVertexId"]
    if next_offset is None and segments:
        assert segments[-1]["endVertexId"] == segments[0]["startVertexId"]
    if not segments:
        return {"solid": solid, "face": face, "boundary": first}
    segment = segments[0]
    requested = [face_id, segment["edgeId"]]
    if segment["startVertexId"]:
        requested.append(segment["startVertexId"])
    batch = call(port, "cst_get_entities", {"ids": requested})
    assert [item["id"] for item in batch["items"]] == requested
    adjacent = call(port, "cst_get_adjacency", {"id": segment["edgeId"], "relation": "faces"})
    assert face_id in adjacent["ids"]
    filtered = call(port, "cst_list_entities", {"solidId": solid_id, "type": "face", "geometryType": face["surfaceType"]})
    assert face_id in filtered["ids"]
    return {"solid": solid, "face": face, "boundary": first, "entities": batch["items"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--output")
    args = ap.parse_args()
    call(args.port, "cst_connect")
    call(args.port, "acis_connect")
    solids = all_solids(args.port)
    if args.fixture:
        assert solids == [], "fixture requires an empty disposable project"
        call(args.port, "cst_vba", {"header": "live_brep_fixture", "code": brick("boxA", 0) + '\n' + brick("方块B", 20)})
        solids = all_solids(args.port)
        assert [s["name"] for s in solids] == ["memory_test:boxA", "memory_test:方块B"]
        for s in solids:
            assert {k:s["counts"][k] for k in ("vertices","edges","faces","coedges")} == {
                "vertices":8,"edges":12,"faces":6,"coedges":24}
        example = check_queries(args.port, solids[0])
        stable_id = call(args.port, "cst_list_entities", {"solidId": solids[1]["id"], "type": "face", "limit": 1})["ids"][0]
        call(args.port, "cst_connect")
        assert all_solids(args.port) == solids
        call(args.port, "cst_local_modify", {"shape": solids[0]["name"], "faceId": 1, "op": "offset", "amount": 2})
        call(args.port, "cst_get_entity", {"id": example["face"]["id"]}, expect_error="STALE_ENTITY_ID")
        fresh = call(args.port, "cst_list_entities", {"solidId": solids[0]["id"], "type": "face", "limit": 1})
        assert fresh["ids"][0] != example["face"]["id"]
        call(args.port, "cst_vba", {"header": "live_brep_delete_fixture", "code": 'Solid.Delete "memory_test:boxA"'})
        call(args.port, "cst_get_entity", {"id": solids[0]["id"]}, expect_error="ENTITY_NOT_FOUND")
        assert call(args.port, "cst_get_entity", {"id": stable_id})["id"] == stable_id
        solids = all_solids(args.port)
    example = check_queries(args.port, solids[0]) if solids else None
    call(args.port, "cst_get_entity", {"id": "face:unknown:0:unknown"}, expect_error="INVALID_ENTITY_ID")
    totals = Counter()
    for solid in solids: totals.update(solid["counts"])
    report = {"ok": True, "solids": solids, "counts": dict(totals), "example": example,
              "queries": len(REPLIES), "maxReplyBytes": max(reply["bytes"] for reply in REPLIES)}
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "solids": len(solids), "counts": dict(totals),
                      "queries": len(REPLIES), "maxReplyBytes": report["maxReplyBytes"]}, ensure_ascii=True))


if __name__=="__main__":main()
