"""Selection protocol tests; no CST instance needed."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bridge"))
from selection import parse_selection


def h(value):
    return value.encode("utf-16-be").hex()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            "TREE\t0\t%s\t%s\t%s" % (h("Components\\组件\\实体"), h("组件:实体"), h("PEC")),
            "FACE\t1\t%s\t7\t100" % h("组件:实体"),
            "EDGE\t2\t%s\t11\t3" % h("组件:实体"),
            "POINT\t3\t-1E-9\t2.5\t30",
        ]

    def test_mixed_selection_keeps_unicode_native_ids_and_point_identity(self):
        result = parse_selection(["BEGIN\t1\t1\t1\t1"] + self.rows + ["END"], 0, 50)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["counts"], {"treeItems": 1, "faces": 1, "edges": 1, "points": 1})
        tree, face, edge, point = result["items"]
        self.assertEqual(tree["solidName"], "组件:实体")
        self.assertEqual(face["cstFaceId"], 7)
        self.assertEqual(face["area"], 100)
        self.assertEqual(edge["cstEdgeId"], 11)
        self.assertEqual(edge["cstStartVertexId"], 3)
        self.assertEqual(point["position"], [-1e-9, 2.5, 30])
        self.assertEqual(point["type"], "point")
        self.assertTrue(all("id" not in item for item in result["items"]))

    def test_pages_keep_global_order_and_category_pick_indices(self):
        result = parse_selection(["BEGIN\t1\t1\t1\t1"] + self.rows[1:3] + ["END"], 1, 2)
        self.assertEqual(result["nextOffset"], 3)
        self.assertEqual([item["pickIndex"] for item in result["items"]], [0, 0])
        last = parse_selection(["BEGIN\t1\t1\t1\t1", self.rows[3], "END"], 3, 2)
        self.assertIsNone(last["nextOffset"])
        self.assertEqual(parse_selection(["BEGIN\t1\t1\t1\t1", "END"], 99, 5)["items"], [])

    def test_non_geometry_tree_item_is_not_reported_as_a_solid(self):
        result = parse_selection(["BEGIN\t1\t0\t0\t0", "TREE\t0\t%s\t\t" % h("1D Results"), "END"], 0, 50)
        self.assertEqual(result["items"][0]["type"], "tree_item")
        self.assertNotIn("solidName", result["items"][0])

    def test_missing_edge_endpoint_is_null(self):
        result = parse_selection(["BEGIN\t0\t0\t1\t0", "EDGE\t0\t%s\t1\t-1" % h("component:circle"), "END"], 0, 50)
        self.assertIsNone(result["items"][0]["cstStartVertexId"])

    def test_partial_out_of_order_or_nonfinite_data_is_rejected(self):
        cases = [[], ["BEGIN\t0\t0\t0\t0"], ["BEGIN\t-1\t0\t0\t0", "END"],
                 ["BEGIN\t1\t1\t1\t1", self.rows[1], "END"],
                 ["BEGIN\t0\t0\t0\t1", "POINT\t0\tnan\t0\t0", "END"],
                 ["BEGIN\t0\t1\t0\t0", "FACE\t0\t%s\t1\tinf" % h("component:solid"), "END"],
                 ["BEGIN\t0\t0\t0\t1", "ERROR\t0", "END"]]
        for lines in cases:
            with self.subTest(lines=lines):
                with self.assertRaises(RuntimeError):
                    parse_selection(lines, 0, 50)


if __name__ == "__main__":
    unittest.main()
