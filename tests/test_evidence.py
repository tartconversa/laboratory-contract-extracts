"""证据形态测试：定量、区间、无结果、样本破坏、测法不适用互不替代。"""

import unittest

from factware.enums import EvidenceKind
from factware.evidence import evaluate_result, latest_results
from factware.ingest import load_handover
from factware.lineage import ShareGraph

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples"


class EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handover = load_handover(ROOT)
        cls.lot_matrix = {line.lot: line.matrix for line in cls.handover.orders}
        cls.methods = {m.method: m for m in cls.handover.methods}
        cls.lines = {line.line: line for line in cls.handover.orders}

    def evidence_for(self, result_id, line_id, as_of):
        graph = ShareGraph(self.handover, as_of, self.lot_matrix)
        result = latest_results(self.handover.results, as_of)[result_id]
        return evaluate_result(result, self.lines[line_id], graph, self.methods)

    def test_quantitative_conforms(self):
        evidence = self.evidence_for("F02", "OL-A", 3)
        self.assertEqual(evidence.kind, EvidenceKind.QUANTITATIVE)
        self.assertTrue(evidence.is_compliant_evidence)
        self.assertEqual((evidence.interval.lower, evidence.interval.upper), (4.0, 4.0))

    def test_below_limit_yields_interval_not_zero(self):
        evidence = self.evidence_for("F04", "OL-B", 3)
        self.assertEqual(evidence.kind, EvidenceKind.INTERVAL)
        self.assertEqual((evidence.interval.lower, evidence.interval.upper), (0.0, 5.5))
        self.assertTrue(evidence.is_compliant_evidence)

    def test_retracted_is_no_result(self):
        # arrival 5: F01 修订为 retracted
        evidence = self.evidence_for("F01", "OL-C", 5)
        self.assertEqual(evidence.kind, EvidenceKind.NO_RESULT)
        self.assertIsNone(evidence.interval)
        self.assertFalse(evidence.is_compliant_evidence)

    def test_tainted_share_is_destroyed_evidence(self):
        evidence = self.evidence_for("F03", "OL-A", 8)
        self.assertEqual(evidence.kind, EvidenceKind.SAMPLE_DESTROYED)
        self.assertEqual(evidence.reason, "tainted:S01")

    def test_wrong_matrix_is_method_inapplicable(self):
        # F17: PP 基质用 PE 方法 M2
        evidence = self.evidence_for("F17", "OL-E", 4)
        self.assertEqual(evidence.kind, EvidenceKind.METHOD_INAPPLICABLE)
        self.assertIn("method:matrix", evidence.reason)

    def test_latest_revision_wins(self):
        rev1 = latest_results(self.handover.results, 3)["F01"]
        rev2 = latest_results(self.handover.results, 5)["F01"]
        self.assertEqual(rev1.revision, 1)
        self.assertEqual(rev2.revision, 2)


if __name__ == "__main__":
    unittest.main()
