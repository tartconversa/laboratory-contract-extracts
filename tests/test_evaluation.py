"""独立性账本与组合包装评价测试。"""

import unittest

from factware.enums import SampleStatus
from factware.evaluation import IndependenceLedger, evaluate_groups
from factware.ingest import load_handover
from factware.lineage import ShareGraph
from factware.models import Handover

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples"


class IndependenceLedgerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handover = load_handover(ROOT)
        cls.lot_matrix = {line.lot: line.matrix for line in cls.handover.orders}

    def graph(self, as_of=4):
        return ShareGraph(self.handover, as_of, self.lot_matrix)

    def test_derivative_cannot_reuse_consumed_share(self):
        ledger = IndependenceLedger()
        graph = self.graph()
        ledger.consume("S01", graph, "G/OL-X")
        # S11、S13 是 S01 的派生物，不能另立资格
        self.assertIsNotNone(ledger.block_reason("S11", graph, "G"))
        self.assertIsNotNone(ledger.block_reason("S13", graph, "G"))

    def test_sibling_aliquots_are_independent(self):
        ledger = IndependenceLedger()
        graph = self.graph()
        ledger.consume("S11", graph, "G/OL-X")
        # S13 是 S01 的另一分取支，与 S11 互相独立
        self.assertIsNone(ledger.block_reason("S13", graph, "G"))
        # 但 S01 本身作为 S11 的父样，其独立资格不被 S11 消耗锁死
        self.assertIsNone(ledger.block_reason("S01", graph, "G"))

    def test_same_share_cannot_serve_two_qualifications_in_group(self):
        ledger = IndependenceLedger()
        graph = self.graph()
        ledger.consume("S12", graph, "G/OL-1")
        self.assertIsNotNone(ledger.block_reason("S12", graph, "G"))

    def test_groups_have_separate_independence_scopes(self):
        ledger = IndependenceLedger()
        graph = self.graph(8)
        ledger.consume("S12", graph, "K-28/OL-A")
        # 另一采购组可独立使用同批实物取得自己的证据
        self.assertIsNone(ledger.block_reason("S12", graph, "K-44"))

    def test_pooled_share_cannot_act_as_second_independent_share(self):
        ledger = IndependenceLedger()
        graph = self.graph(3)
        ledger.mark_pooled("pool:S11:L611:L612", "S11", graph, "K-44")
        # 同一混合样在同组内不能再充当另一份独立试样
        self.assertIsNotNone(ledger.block_reason("S11", graph, "K-44"))
        # 覆盖登记幂等：同组重复登记同一覆盖不报错、不重复计用量
        ledger.mark_pooled("pool:S11:L611:L612", "S11", graph, "K-44")
        self.assertEqual(ledger.consumed_in("K-44"), frozenset({"S11"}))


class GroupEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handover = load_handover(ROOT)
        cls.lot_matrix = {line.lot: line.matrix for line in cls.handover.orders}

    def verdict(self, as_of):
        graph = ShareGraph(self.handover, as_of, self.lot_matrix)
        return evaluate_groups(self.handover, graph, as_of)

    def test_pooled_group_qualified_by_one_mixed_coverage(self):
        verdicts = self.verdict(4)
        k44 = verdicts["K-44"]
        self.assertTrue(k44.compliant)
        self.assertTrue(k44.pooled)
        self.assertTrue(all(line.pooled_coverage_id for line in k44.lines))

    def test_combined_packaging_requires_every_component(self):
        # K-28 = OL-A(2 份) + OL-B(1 份)，任一缺证整组不合格
        verdicts = self.verdict(3)
        self.assertTrue(verdicts["K-28"].compliant)
        blocked = self.verdict(5)
        self.assertFalse(blocked["K-28"].compliant)

    def test_two_independent_shares_required(self):
        verdicts = self.verdict(8)
        ola = next(line for line in verdicts["K-28"].lines if line.line.line == "OL-A")
        self.assertEqual(ola.required, 2)
        # S12 + S16 两个独立分取支
        self.assertEqual(ola.independent_shares, 2)
        self.assertTrue(ola.compliant)

    def test_method_inapplicable_blocks_group(self):
        verdicts = self.verdict(8)
        self.assertFalse(verdicts["K-47"].compliant)
        codes = verdicts["K-47"].missing
        self.assertTrue(any(reason.code == "evidence_method_inapplicable" for reason in codes))


if __name__ == "__main__":
    unittest.main()
