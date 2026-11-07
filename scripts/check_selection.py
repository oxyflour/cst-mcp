"""Read current selection; --fixture changes selection/geometry in an empty scratch project.

  py -3.12 scripts/check_selection.py --port 8765 --output out/selection.json
  py -3.12 scripts/check_selection.py --port 8770 --fixture
"""
import argparse
import json
from pathlib import Path

from check_live_brep import call, brick


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--output")
    args = ap.parse_args()
    call(args.port, "cst_connect")
    # Selection is available before calling acis_connect.
    before = call(args.port, "cst_get_selection")
    if args.fixture:
        call(args.port, "acis_connect")
        assert call(args.port, "cst_list_solids")["total"] == 0, "fixture requires an empty scratch project"
        name = "memory_test:方块"
        call(args.port, "cst_vba", {"header": "selection_fixture", "code": brick("方块", 0)})
        code = '\n'.join([
            "Pick.ClearAllPicks",
            'SelectTreeItem("Components\\memory_test\\方块")',
            'Pick.PickFaceFromId "' + name + '", "1"',
            'Pick.PickEdgeFromPoint "' + name + '", "10", "0", "5"',
            'Pick.PickPointFromCoordinates "10", "0", "0"',
        ])
        call(args.port, "cst_vba", {"header": "selection_pick_fixture", "code": code})
        before = call(args.port, "cst_get_selection")
        picked = {kind: [item for item in before["items"] if item["type"] == kind]
                  for kind in ("solid", "face", "edge", "point")}
        assert picked["solid"] and picked["solid"][0]["solidName"] == name, before
        assert len(picked["face"]) == 1 and picked["face"][0]["cstFaceId"] == 1, before
        assert abs(picked["face"][0]["area"] - 100) < 1e-6, before
        assert len(picked["edge"]) == 1 and picked["edge"][0]["cstEdgeId"] >= 0, before
        assert len(picked["point"]) == 1 and picked["point"][0]["position"] == [10, 0, 0], before
    again = call(args.port, "cst_get_selection")
    assert again == before, "query changed selection or returned unstable state"
    items, offset = [], 0
    while offset is not None:
        page = call(args.port, "cst_get_selection", {"offset": offset, "limit": 1})
        assert page["counts"] == before["counts"]
        items.extend(page["items"])
        offset = page["nextOffset"]
    assert items == before["items"]
    assert call(args.port, "cst_get_selection", {"offset": before["total"] + 1})["items"] == []
    if args.output:
        Path(args.output).write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "total": before["total"], "counts": before["counts"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
