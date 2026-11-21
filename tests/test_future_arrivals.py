"""后续到货延续测试：新批次按公开资料合同走完整条链。

合成一份新交接目录，模拟：
- 新订单行组 K-52 与新份额 S31/S32 到货；
- 一次补测先用错基质方法（不适用），再用正确方法补测合格；
- 结论交付 offered -> accepted，签收后污染触发冻结。
"""

import csv
import tempfile
import unittest
from pathlib import Path

from factware.ingest import load_handover
from factware.warehouse import Warehouse

ROOT = Path(__file__).resolve().parents[1] / "examples"


def _write(path: Path, name: str, header: list[str], rows: list[list]) -> None:
    with (path / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


class FutureArrivalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        self._build()
        self.warehouse = Warehouse.from_directory(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def _build(self) -> None:
        # 复制既有方法与分取基线，新增独立的新批次故事。
        for name in ("methods.csv",):
            (self.path / name).write_text(
                (ROOT / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        _write(self.path, "orders.csv",
               ["group", "line", "material", "lot", "matrix", "metric", "unit",
                "upper", "replicates", "pooled"],
               [["K-52", "OL-Z", "薄膜", "L900", "PE", "migration", "mg/kg", "5", "1", "no"]])
        _write(self.path, "samples.csv",
               ["arrival", "sample", "source_lots", "parent", "grams", "status"],
               [[1, "S31", "L900", "", 40, "available"],
                [4, "S31", "L900", "", 40, "tainted"],
                [4, "S32", "L900", "", 40, "available"]])
        _write(self.path, "sampling.csv",
               ["child", "parent", "grams"], [])
        _write(self.path, "test_results.csv",
               ["arrival", "result", "revision", "at", "sample", "method", "value", "status"],
               # arrival 2：错用 PP 方法 M3（基质不覆盖 PE）
               [[2, "F90", 1, "2026-10-20", "S31", "M3", 2, "detected"],
                # arrival 3：改用 PE 方法 M2，定量 3，合格
                [3, "F91", 1, "2026-10-21", "S31", "M2", 3, "detected"],
                # arrival 5：替代份额 S32 补测，未检出 4，区间合格
                [5, "F92", 1, "2026-10-22", "S32", "M2", 4, "below"]])
        _write(self.path, "dispatch.csv",
               ["arrival", "dispatch", "sample", "lab", "grams", "state"],
               [[2, "SA90", "S31", "LAB-A", 10, "received"],
                [5, "SA92", "S32", "LAB-A", 10, "received"]])
        _write(self.path, "release.csv",
               ["arrival", "release", "group", "receiver", "kind"],
               [[3, "AR90", "K-52", "WH-C", "offered"],
                [4, "AR90", "K-52", "WH-C", "accepted"]])

    def test_wrong_method_blocks_then_correct_method_passes(self):
        self.assertFalse(self.warehouse.snapshot(2).groups["K-52"].compliant)
        verdict3 = self.warehouse.snapshot(3).groups["K-52"]
        self.assertTrue(verdict3.compliant)

    def test_accepted_then_tainted_freezes_and_retest_restores(self):
        # arrival 4：S31 污染，已入库 -> 冻结通知
        notices4 = [n for n in self.warehouse.snapshot(4).notifications if n.arrival == 4]
        self.assertEqual([n.kind for n in notices4], ["freeze_recheck"])
        self.assertFalse(self.warehouse.snapshot(4).groups["K-52"].compliant)
        # 历史合格证明保留
        self.assertTrue(self.warehouse.snapshot(3).groups["K-52"].compliant)
        # arrival 5：独立替代份额 S32 补测恢复
        self.assertTrue(self.warehouse.snapshot(5).groups["K-52"].compliant)
        self.assertEqual(
            [b.batch_id for b in self.warehouse.claimable_batches()],
            ["B05-K-52"],
        )

    def test_chain_is_fully_traceable(self):
        refs = self.warehouse.latest().groups["K-52"].evidence_refs
        self.assertTrue(any(ref.result == "F92" and ref.sample == "S32" for ref in refs))
        impact = self.warehouse.impact("S31")
        self.assertEqual(impact["subtree"], ["S31"])
        self.assertTrue(any(g["group"] == "K-52" for g in impact["affected_groups"]))

    def test_worklist_empty_once_group_qualified(self):
        from factware.lineage import ShareGraph
        from factware.worklist import build_worklist
        handover = load_handover(self.path)
        graph = ShareGraph(handover, 5, {line.lot: line.matrix for line in handover.orders})
        self.assertEqual(build_worklist(handover, graph, 5), ())


if __name__ == "__main__":
    unittest.main()
