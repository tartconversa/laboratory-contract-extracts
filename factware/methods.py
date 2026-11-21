"""检测方法对合同规定的覆盖判断。

实验室声称新方法可以替代旧方法时，仍须逐项核对五个维度是否覆盖合同：
材料基质、测项、量纲（报告单位经 factor 到合同单位的换算路径）、
报告日是否在有效期内、检出限是否足以支撑合格范围。
任一维度不覆盖即判测法不适用，该结果不能作为合格证据。
"""

from dataclasses import dataclass, field

from factware.models import Method
from factware.units import below_limit_interval


@dataclass(frozen=True)
class MethodAssessment:
    """一次方法适用性核对的结论与失败维度。"""

    method: str
    covered: bool
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason(self) -> str | None:
        return None if self.covered else "method:" + "+".join(self.failures)


# 维度键固定，便于测试与缺证原因检索。
DIM_MATRIX = "matrix"
DIM_METRIC = "metric"
DIM_UNIT = "unit"
DIM_VALIDITY = "validity"
DIM_LIMIT = "detection_limit"


def assess_method(
    method: Method,
    *,
    contract_matrix: str,
    contract_metric: str,
    report_date: str,
    contract_upper: float | None = None,
    reported_limit: float | None = None,
) -> MethodAssessment:
    """核对方法是否覆盖合同规定。

    ``reported_limit`` 为未检出结果登记的检出限（报告单位）；
    提供时连同合同上限一起核对检出限覆盖能力。
    """
    failures: list[str] = []
    if contract_matrix not in method.matrices:
        failures.append(DIM_MATRIX)
    if method.metric != contract_metric:
        failures.append(DIM_METRIC)
    if method.factor <= 0:
        failures.append(DIM_UNIT)
    if not method.valid_on(report_date):
        failures.append(DIM_VALIDITY)
    if reported_limit is not None and contract_upper is not None:
        supported = below_limit_interval(reported_limit, method.factor)
        if not supported.within(contract_upper):
            failures.append(DIM_LIMIT)
    return MethodAssessment(
        method=method.method,
        covered=not failures,
        failures=tuple(failures),
    )
