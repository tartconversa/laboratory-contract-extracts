"""量纲与区间语义。

未检出（below）绝不写成零：它支持的是 ``[0, 检出限]`` 区间。
只有整段区间落入合同合格范围，未检出证据才能证明符合。
方法给出的 factor 把报告单位换算到合同单位。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    """结果在合同单位下支持的真实值闭区间。"""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.lower < 0 or self.upper < self.lower:
            raise ValueError(f"非法区间：[{self.lower}, {self.upper}]")

    def within(self, upper_limit: float) -> bool:
        """整段区间是否落入 [0, 上限] 合格范围。"""
        return self.lower >= 0 and self.upper <= upper_limit


def to_contract_value(value: float, factor: float) -> float:
    """把报告单位数值换算到合同单位。"""
    if factor <= 0:
        raise ValueError(f"换算因子必须为正：{factor}")
    return value * factor


def quantitative_interval(value: float, factor: float) -> Interval:
    """定量结果退化为单点区间。"""
    converted = to_contract_value(value, factor)
    return Interval(converted, converted)


def below_limit_interval(limit: float, factor: float) -> Interval:
    """未检出：真实值落在 [0, 检出限（合同单位）]。"""
    return Interval(0.0, to_contract_value(limit, factor))
