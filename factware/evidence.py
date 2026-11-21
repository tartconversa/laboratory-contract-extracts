"""检验证据评价：把结果事实转成带形态、区间和适用性的证据。

四类证据严格区分，不可互相替代：
- quantitative 定量；interval 未检出（区间，不写成零）；
- no_result 无结果（撤回）；sample_destroyed 样本破坏/污染；
- method_inapplicable 测法不适用。
"""

from dataclasses import dataclass, field

from factware.enums import EvidenceKind, ResultStatus
from factware.lineage import ShareGraph, ShareState
from factware.methods import assess_method
from factware.models import Method, OrderLine, TestResult
from factware.units import Interval, below_limit_interval, quantitative_interval


@dataclass(frozen=True)
class Evidence:
    """一份可追溯到结果、份额与方法的证据评价。"""

    result_id: str
    revision: int
    sample: str
    method: str
    kind: EvidenceKind
    interval: Interval | None
    conforms: bool
    arrival: int
    report_date: str
    reason: str | None = None
    detail: dict = field(default_factory=dict)

    @property
    def is_compliant_evidence(self) -> bool:
        """是否可用于证明该订单行符合。"""
        return self.conforms and self.kind in {EvidenceKind.QUANTITATIVE, EvidenceKind.INTERVAL}


def latest_results(results: tuple[TestResult, ...], as_of: int) -> dict[str, TestResult]:
    """取每个 result 身份在该时刻之前的最新修订。"""
    latest: dict[str, TestResult] = {}
    for result in results:
        if result.arrival > as_of:
            continue
        prior = latest.get(result.result)
        if prior is None or result.revision > prior.revision:
            latest[result.result] = result
    return latest


def evaluate_result(
    result: TestResult,
    line: OrderLine,
    graph: ShareGraph,
    methods: dict[str, Method],
) -> Evidence:
    """评价单份结果对某订单行的证据意义。"""
    state: ShareState = graph.state(result.sample)
    method = methods[result.method]
    matrix = graph.derive_matrix(result.sample)

    # 撤回结果优先表达为无结果：报告自身撤回是独立事实，
    # 即便份额随后污染，也不能抹掉“这份结果已无效”的无结果证据。
    if result.status is ResultStatus.RETRACTED or result.value is None:
        return Evidence(
            result_id=result.result, revision=result.revision, sample=result.sample,
            method=result.method, kind=EvidenceKind.NO_RESULT,
            interval=None, conforms=False, arrival=result.arrival,
            report_date=result.at, reason="retracted",
        )

    # 样本破坏/污染：份额及其派生链不可再支撑任何结论。
    if state.tainted:
        return Evidence(
            result_id=result.result, revision=result.revision, sample=result.sample,
            method=result.method, kind=EvidenceKind.SAMPLE_DESTROYED,
            interval=None, conforms=False, arrival=result.arrival,
            report_date=result.at, reason=f"tainted:{state.tainted_by}",
            detail={"tainted_by": state.tainted_by},
        )

    limit = result.value if result.status is ResultStatus.BELOW else None
    assessment = assess_method(
        method,
        contract_matrix=matrix,
        contract_metric=line.metric,
        report_date=result.at,
        contract_upper=line.upper,
        reported_limit=limit,
    )
    if not assessment.covered:
        return Evidence(
            result_id=result.result, revision=result.revision, sample=result.sample,
            method=result.method, kind=EvidenceKind.METHOD_INAPPLICABLE,
            interval=None, conforms=False, arrival=result.arrival,
            report_date=result.at, reason=assessment.reason,
            detail={"failures": list(assessment.failures), "share_matrix": matrix},
        )

    if result.status is ResultStatus.BELOW:
        interval = below_limit_interval(result.value, method.factor)
        kind = EvidenceKind.INTERVAL
    else:
        interval = quantitative_interval(result.value, method.factor)
        kind = EvidenceKind.QUANTITATIVE
    conforms = interval.within(line.upper)
    return Evidence(
        result_id=result.result, revision=result.revision, sample=result.sample,
        method=result.method, kind=kind, interval=interval,
        conforms=conforms, arrival=result.arrival, report_date=result.at,
        reason=None if conforms else "exceeds_spec",
        detail={"contract_unit": line.unit, "upper": line.upper},
    )
