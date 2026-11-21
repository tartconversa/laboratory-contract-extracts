"""量纲与区间语义测试：未检出不写成零，整段落入合格范围才算符合。"""

import unittest

from factware.units import (
    Interval,
    below_limit_interval,
    quantitative_interval,
    to_contract_value,
)


class UnitsTest(unittest.TestCase):
    def test_factor_converts_to_contract_unit(self):
        # M4: ug/kg -> mg/kg，factor 0.001
        self.assertEqual(to_contract_value(5500, 0.001), 5.5)

    def test_below_limit_is_a_range_not_zero(self):
        interval = below_limit_interval(4, 1.0)
        self.assertEqual((interval.lower, interval.upper), (0.0, 4.0))

    def test_below_limit_range_must_fit_wholly_in_spec(self):
        # 检出限换算后 5.5，上限 7：整段 [0,5.5] 合格
        self.assertTrue(below_limit_interval(5500, 0.001).within(7.0))
        # 检出限本身已超过上限：不能用于证明符合
        self.assertFalse(below_limit_interval(8.0, 1.0).within(7.0))

    def test_quantitative_is_a_point_interval(self):
        self.assertEqual(quantitative_interval(4, 1.0), Interval(4.0, 4.0))
        self.assertTrue(quantitative_interval(4, 1.0).within(5.0))
        self.assertFalse(quantitative_interval(6, 1.0).within(5.0))

    def test_non_positive_factor_rejected(self):
        with self.assertRaises(ValueError):
            to_contract_value(1, 0)

    def test_invalid_interval_rejected(self):
        with self.assertRaises(ValueError):
            Interval(1, 0.5)


if __name__ == "__main__":
    unittest.main()
