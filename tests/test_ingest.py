"""交接资料摄入校验测试：身份、枚举、引用与修订号。"""

import tempfile
import unittest
from pathlib import Path

from factware.ingest import HandoverError, load_handover

ROOT = Path(__file__).resolve().parents[1] / "examples"

HEADER = {
    "orders.csv": "group,line,material,lot,matrix,metric,unit,upper,replicates,pooled",
    "samples.csv": "arrival,sample,source_lots,parent,grams,status",
    "methods.csv": "method,matrix,metric,reported_unit,factor,from,until",
    "test_results.csv": "arrival,result,revision,at,sample,method,value,status",
    "dispatch.csv": "arrival,dispatch,sample,lab,grams,state",
    "release.csv": "arrival,release,group,receiver,kind",
    "sampling.csv": "child,parent,grams",
}


class IngestTest(unittest.TestCase):
    def test_supplied_handover_loads(self):
        handover = load_handover(ROOT)
        self.assertTrue(handover.orders and handover.results)
        self.assertIn(5, handover.arrivals)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "orders.csv").write_text(HEADER["orders.csv"] + "\n", encoding="utf-8")
            with self.assertRaises(HandoverError):
                load_handover(tmp)

    def test_unknown_sample_reference_rejected(self):
        rows = {
            "test_results.csv": "1,F99,1,2026-10-15,SXX,M1,1,detected\n",
        }
        with self._handover(rows) as handover:
            with self.assertRaises(HandoverError):
                load_handover(handover)

    def test_unknown_enum_rejected(self):
        rows = {"samples.csv": "1,S99,L611,,10,on_fire\n"}
        with self._handover(rows) as path:
            with self.assertRaises(HandoverError):
                load_handover(path)

    def test_non_increasing_revision_rejected(self):
        rows = {
            "test_results.csv": (
                "3,F01,1,2026-10-15,S11,M1,6,below\n"
                "5,F01,1,2026-10-15,S11,M1,,retracted\n"
            ),
        }
        with self._handover(rows) as path:
            with self.assertRaises(HandoverError):
                load_handover(path)

    def test_duplicate_order_identity_rejected(self):
        rows = {
            "orders.csv": (
                HEADER["orders.csv"] + "\n"
                "K-1,OL-A,薄膜,L611,PE,migration,mg/kg,5,1,no\n"
                "K-1,OL-A,薄膜,L611,PE,migration,mg/kg,5,1,no\n"
            ),
        }
        with self._handover(rows) as path:
            with self.assertRaises(HandoverError):
                load_handover(path)

    def _handover(self, overrides: dict[str, str]):
        base = {
            "orders.csv": HEADER["orders.csv"] + "\nK-1,OL-A,薄膜,L611,PE,migration,mg/kg,5,1,no\n",
            "samples.csv": HEADER["samples.csv"] + "\n1,S11,L611,,20,available\n",
            "methods.csv": HEADER["methods.csv"] + "\nM1,PE,migration,mg/kg,1,2026-08-01,\n",
            "test_results.csv": "",
            "dispatch.csv": "",
            "release.csv": "",
            "sampling.csv": HEADER["sampling.csv"] + "\n",
        }
        base.update(overrides)
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name)
        for name, content in base.items():
            (path / name).write_text(content, encoding="utf-8")
        return _TempHandover(path, tmp)


class _TempHandover:
    def __init__(self, path, tmp):
        self.path = path
        self._tmp = tmp

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        self._tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
