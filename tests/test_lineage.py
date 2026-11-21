"""份额谱系测试：分取克数、污染传播、混合基质与独立根。"""

import unittest

from factware.ingest import load_handover
from factware.lineage import ShareGraph

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1] / "examples"


class LineageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handover = load_handover(ROOT)
        cls.lot_matrix = {line.lot: line.matrix for line in cls.handover.orders}

    def graph(self, as_of):
        return ShareGraph(self.handover, as_of, self.lot_matrix)

    def test_remaining_grams_after_withdrawal(self):
        graph = self.graph(4)
        # S01 40g，分取 S11(10) 与 S13(12)，剩 18g
        self.assertEqual(graph.state("S01").remaining_grams, 18.0)
        # S02 40g，分取 S12 10g，剩 30g
        self.assertEqual(graph.state("S02").remaining_grams, 30.0)

    def test_roots_follow_parent_chain(self):
        graph = self.graph(4)
        self.assertEqual(graph.roots("S11"), frozenset({"S01", "S03"}))
        self.assertEqual(graph.roots("S12"), frozenset({"S02"}))

    def test_subtree_includes_derivatives(self):
        graph = self.graph(8)
        self.assertEqual(graph.subtree("S01"), frozenset({"S01", "S11", "S13"}))

    def test_taint_propagates_to_derivatives(self):
        graph = self.graph(8)  # arrival 5 将 S01 更正为 tainted
        self.assertTrue(graph.state("S01").tainted)
        self.assertTrue(graph.state("S11").tainted)
        self.assertTrue(graph.state("S13").tainted)
        self.assertEqual(graph.state("S13").tainted_by, "S01")
        # 不同根的份额不受影响
        self.assertFalse(graph.state("S02").tainted)
        self.assertFalse(graph.state("S12").tainted)

    def test_mixed_matrix_derivation(self):
        graph = self.graph(4)
        self.assertEqual(graph.derive_matrix("S11"), "mixed-PE")
        self.assertEqual(graph.derive_matrix("S12"), "PE")

    def test_late_status_correction_visible_only_after_arrival(self):
        before = self.graph(4)
        after = self.graph(5)
        self.assertFalse(before.state("S01").tainted)
        self.assertTrue(after.state("S01").tainted)

    def test_usable_shares_exclude_tainted_and_empty(self):
        graph = self.graph(8)
        usable = {state.sample.sample for state in graph.usable_shares()}
        self.assertNotIn("S01", usable)
        self.assertNotIn("S11", usable)
        self.assertIn("S16", usable)
        self.assertIn("S03", usable)

    def test_remaining_grams_never_negative(self):
        # 任何份额剩余克数都被钳制为非负
        graph = self.graph(8)
        for sample_id in graph.sample_ids:
            self.assertGreaterEqual(graph.state(sample_id).remaining_grams, 0)


if __name__ == "__main__":
    unittest.main()
