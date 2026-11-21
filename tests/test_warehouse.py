"""事实仓时间线测试：重放、通知、交付批、冻结、恢复与级联。"""

import unittest

from factware.enums import ReleaseKind
from factware.warehouse import Warehouse
from factware.worklist import build_worklist
from factware.ingest import load_handover
from factware.lineage import ShareGraph

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples"


class WarehouseTimelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wh = Warehouse.from_directory(ROOT)
        cls.handover = load_handover(ROOT)
        cls.lot_matrix = {line.lot: line.matrix for line in cls.handover.orders}

    def status(self, arrival, group):
        return self.wh.snapshot(arrival).groups[group]

    def test_groups_blocked_before_results_arrive(self):
        for group in ("K-28", "K-44", "K-47"):
            self.assertFalse(self.status(2, group).compliant)
        self.assertEqual(self.wh.snapshot(2).outbox, ())

    def test_first_qualified_batches_become_claimable(self):
        snap3 = self.wh.snapshot(3)
        self.assertTrue(self.status(3, "K-28").compliant)
        self.assertTrue(self.status(3, "K-44").compliant)
        claimable = {b.group for b in snap3.outbox if b.claimable}
        self.assertEqual(claimable, {"K-28", "K-44"})

    def test_accepted_credential_kept_but_frozen_on_taint(self):
        # arrival 5：S01 污染，K-28 已入库 -> freeze_recheck
        notices = {n.group: n for n in self.wh.snapshot(5).notifications if n.arrival == 5}
        self.assertEqual(notices["K-28"].kind, "freeze_recheck")
        self.assertEqual(notices["K-28"].accepted_release, "AR21")
        # 冻结批不可再领取入库
        b05 = next(b for b in self.wh.snapshot(5).outbox if b.group == "K-28")
        self.assertFalse(b05.claimable)

    def test_offered_credential_invalidated_when_not_accepted(self):
        notices = {n.group: n for n in self.wh.snapshot(5).notifications if n.arrival == 5}
        self.assertEqual(notices["K-44"].kind, "offer_invalidated")
        self.assertIsNone(notices["K-44"].accepted_release)
        b05 = next(b for b in self.wh.snapshot(5).outbox if b.group == "K-44")
        self.assertFalse(b05.claimable)

    def test_historical_accepted_proof_is_preserved(self):
        # arrival 4 的合格快照在后续污染后仍原样可查
        historical = self.status(4, "K-28")
        self.assertTrue(historical.compliant)
        self.assertTrue(historical.evidence_refs)

    def test_retest_restores_one_order_but_not_the_other(self):
        snap8 = self.wh.snapshot(8)
        self.assertTrue(snap8.groups["K-28"].compliant)   # S12+S16 恢复
        self.assertFalse(snap8.groups["K-44"].compliant)  # L612 独立份额仍缺
        self.assertEqual(
            [b.batch_id for b in self.wh.claimable_batches()],
            ["B08-K-28"],
        )

    def test_freeze_clears_after_recovery(self):
        self.assertFalse(self.wh._memories["K-28"].frozen)

    def test_impact_cascade_locates_all_affected_facts(self):
        impact = self.wh.impact("S01")
        self.assertEqual(set(impact["subtree"]), {"S01", "S11", "S13"})
        groups = {item["group"] for item in impact["affected_groups"]}
        self.assertIn("K-28", groups)
        self.assertIn("K-44", groups)
        # 通知历史按到达批次与明细去重
        arrivals = [entry["arrival"] for entry in impact["notification_history"]]
        self.assertEqual(arrivals, [5])
        details = impact["notification_history"][0]["notifications"]
        self.assertEqual(len(details), len(set(details)))

    def test_dispatch_hold_blocks_reuse_until_cancel_acknowledged(self):
        graph5 = ShareGraph(self.handover, 5, self.lot_matrix)
        work5 = build_worklist(self.handover, graph5, 5)
        s16 = next(
            c for item in work5 for c in item.candidates if c.sample == "S16"
        )
        self.assertEqual(s16.blocker, "dispatch_held")
        # arrival 7 场所确认撤销后，S16 在 arrival 8 可被新检验使用
        graph8 = ShareGraph(self.handover, 8, self.lot_matrix)
        work8 = build_worklist(self.handover, graph8, 8)
        held = [c for item in work8 for c in item.candidates if c.sample == "S16"]
        self.assertTrue(all(c.blocker != "dispatch_held" for c in held))

    def test_worklist_points_to_retrievable_physical_shares(self):
        graph = ShareGraph(self.handover, 8, self.lot_matrix)
        worklist = build_worklist(self.handover, graph, 8)
        index = {(item.group, item.line.line): item for item in worklist}
        # OL-D 缺 L612：S03 是可补的独立实物
        old = index[("K-44", "OL-D")]
        self.assertIn("S03", [c.sample for c in old.candidates if c.usable])
        # OL-E 测法不适用：S15 可按 PP 方法补测
        ole = index[("K-47", "OL-E")]
        s15 = next(c for c in ole.candidates if c.sample == "S15")
        self.assertTrue(s15.usable)
        self.assertTrue(
            any(reason.code == "evidence_method_inapplicable" for reason in ole.missing)
        )

    def test_release_writeback_states_are_visible(self):
        kinds = {(r.release, r.kind) for r in self.handover.releases}
        self.assertIn(("AR21", ReleaseKind.ACCEPTED), kinds)
        self.assertIn(("AR22", ReleaseKind.OFFERED), kinds)
        self.assertIn(("AR21", ReleaseKind.CORRECTION_ACK), kinds)

    def test_batches_carry_supersession_chain(self):
        b08 = next(b for b in self.wh.snapshot(8).outbox if b.group == "K-28")
        self.assertIn("B03-K-28", b08.supersedes)
        self.assertIn("B05-K-28", b08.supersedes)


if __name__ == "__main__":
    unittest.main()
