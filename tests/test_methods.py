"""方法覆盖五维测试：基质、测项、量纲、有效期、检出限。"""

import unittest

from factware.methods import (
    DIM_LIMIT,
    DIM_MATRIX,
    DIM_METRIC,
    DIM_UNIT,
    DIM_VALIDITY,
    assess_method,
)
from factware.models import Method


def m1(**overrides):
    params = dict(
        method="MX", matrices=("PE", "mixed-PE"), metric="migration",
        reported_unit="mg/kg", factor=1.0,
        valid_from="2026-08-01", valid_until="2026-11-01",
    )
    params.update(overrides)
    return Method(**params)


class MethodCoverageTest(unittest.TestCase):
    def test_all_dimensions_covered(self):
        result = assess_method(
            m1(), contract_matrix="PE", contract_metric="migration",
            report_date="2026-10-15", contract_upper=5, reported_limit=4,
        )
        self.assertTrue(result.covered)
        self.assertIsNone(result.reason)

    def test_matrix_mismatch_fails(self):
        # F17 场景：PP 试样用了只适用 PE 的方法
        result = assess_method(
            m1(), contract_matrix="PP", contract_metric="migration",
            report_date="2026-10-18",
        )
        self.assertFalse(result.covered)
        self.assertEqual(result.failures, (DIM_MATRIX,))

    def test_mixed_matrix_token_accepted(self):
        result = assess_method(
            m1(), contract_matrix="mixed-PE", contract_metric="migration",
            report_date="2026-10-15",
        )
        self.assertTrue(result.covered)

    def test_metric_mismatch_fails(self):
        result = assess_method(
            m1(), contract_matrix="PE", contract_metric="heavy_metal",
            report_date="2026-10-15",
        )
        self.assertEqual(result.failures, (DIM_METRIC,))

    def test_expired_and_early_method_fail(self):
        self.assertIn(
            DIM_VALIDITY,
            assess_method(m1(), contract_matrix="PE", contract_metric="migration",
                          report_date="2026-11-02").failures,
        )
        self.assertIn(
            DIM_VALIDITY,
            assess_method(m1(), contract_matrix="PE", contract_metric="migration",
                          report_date="2026-07-31").failures,
        )

    def test_open_ended_validity(self):
        method = m1(valid_until=None)
        self.assertTrue(assess_method(
            method, contract_matrix="PE", contract_metric="migration",
            report_date="2030-01-01").covered)

    def test_detection_limit_too_weak_fails(self):
        # 检出限换算后高于合同上限，未检出区间无法整段落入合格范围
        result = assess_method(
            m1(), contract_matrix="PE", contract_metric="migration",
            report_date="2026-10-15", contract_upper=5, reported_limit=6,
        )
        self.assertEqual(result.failures, (DIM_LIMIT,))

    def test_non_positive_factor_fails_unit_dimension(self):
        result = assess_method(
            m1(factor=0), contract_matrix="PE", contract_metric="migration",
            report_date="2026-10-15",
        )
        self.assertIn(DIM_UNIT, result.failures)


if __name__ == "__main__":
    unittest.main()
