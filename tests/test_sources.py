"""核对项目内的合成交接原件。"""
from pathlib import Path
import unittest

from tools.source_inventory import describe, read_records


ROOT = Path(__file__).resolve().parents[1] / "examples"


class SourceFilesTest(unittest.TestCase):
    def test_supplied_files_can_be_read(self):
        report = describe(ROOT)
        self.assertEqual(list(report), ['dispatch.csv', 'methods.csv', 'orders.csv', 'release.csv', 'samples.csv', 'sampling.csv', 'test_results.csv'])
        self.assertTrue(all(item["记录数"] and item["字段"] for item in report.values()))

    def test_supplied_related_records_are_preserved(self):
        for filename, key, value, total in [['orders.csv', 'lot', 'L611', 2], ['samples.csv', 'sample', 'S01', 2], ['release.csv', 'release', 'AR21', 2]]:
            with self.subTest(filename=filename, key=key, value=value):
                records = read_records(ROOT / filename)
                self.assertEqual(sum(str(record.get(key)) == value for record in records), total)
