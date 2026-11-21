"""不可变领域对象：检验请求、分取份额、检测场所与交接事实。

三类身份各自独立：
- 检验请求：订单行组（group/line）；
- 分取数量：试样份额（sample，含分取谱系）；
- 检测场所：实验室（lab，经送检单 dispatch 关联）。
"""

from dataclasses import dataclass, field

from factware.enums import (
    DispatchState,
    ReleaseKind,
    ResultStatus,
    SampleStatus,
)


def _split_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in str(value).split(";") if token.strip())


@dataclass(frozen=True)
class OrderLine:
    """合同订单行：一个订单组内对一种材料/批次的必检承诺。"""

    group: str
    line: str
    material: str
    lot: str
    matrix: str
    metric: str
    unit: str
    upper: float
    replicates: int
    pooled: bool

    @property
    def spec_id(self) -> tuple[str, str]:
        return (self.matrix, self.metric)


@dataclass(frozen=True)
class Sample:
    """实物试样份额，带分取谱系与剩余克数。"""

    arrival: int
    sample: str
    source_lots: tuple[str, ...]
    parents: tuple[str, ...]
    grams: float
    status: SampleStatus

    @classmethod
    def from_row(cls, row: dict) -> "Sample":
        return cls(
            arrival=int(row["arrival"]),
            sample=row["sample"],
            source_lots=_split_tokens(row["source_lots"]),
            parents=_split_tokens(row.get("parent", "")),
            grams=float(row["grams"]),
            status=SampleStatus(row["status"]),
        )

    @property
    def is_mixed(self) -> bool:
        return len(self.source_lots) > 1


@dataclass(frozen=True)
class SamplingLink:
    """分取登记：子样从父样实际取走的克数。"""

    child: str
    parent: str
    grams: float


@dataclass(frozen=True)
class Method:
    """检测方法及其适用范围（基质/测项/量纲/有效期/检出限）。"""

    method: str
    matrices: tuple[str, ...]
    metric: str
    reported_unit: str
    factor: float
    valid_from: str
    valid_until: str | None

    @classmethod
    def from_row(cls, row: dict) -> "Method":
        until = row.get("until") or ""
        return cls(
            method=row["method"],
            matrices=_split_tokens(row["matrix"]),
            metric=row["metric"],
            reported_unit=row["reported_unit"],
            factor=float(row["factor"]),
            valid_from=row["from"],
            valid_until=until or None,
        )

    def valid_on(self, report_date: str) -> bool:
        if report_date < self.valid_from:
            return False
        if self.valid_until and report_date > self.valid_until:
            return False
        return True


@dataclass(frozen=True)
class TestResult:
    """一份检测结果记录（按 revision 保留全部修订，评价时取最新修订）。"""

    arrival: int
    result: str
    revision: int
    at: str
    sample: str
    method: str
    value: float | None
    status: ResultStatus

    @classmethod
    def from_row(cls, row: dict) -> "TestResult":
        raw = row.get("value", "")
        status = ResultStatus(row["status"])
        value = None if not raw or status is ResultStatus.RETRACTED else float(raw)
        return cls(
            arrival=int(row["arrival"]),
            result=row["result"],
            revision=int(row["revision"]),
            at=row["at"],
            sample=row["sample"],
            method=row["method"],
            value=value,
            status=status,
        )


@dataclass(frozen=True)
class Dispatch:
    """送检单：份额送往检测场所的状态事实。"""

    arrival: int
    dispatch: str
    sample: str
    lab: str
    grams: float
    state: DispatchState

    @classmethod
    def from_row(cls, row: dict) -> "Dispatch":
        return cls(
            arrival=int(row["arrival"]),
            dispatch=row["dispatch"],
            sample=row["sample"],
            lab=row["lab"],
            grams=float(row["grams"]),
            state=DispatchState(row["state"]),
        )


@dataclass(frozen=True)
class Release:
    """采购侧签收事实：结论批的交付与入库状态。"""

    arrival: int
    release: str
    group: str
    receiver: str
    kind: ReleaseKind

    @classmethod
    def from_row(cls, row: dict) -> "Release":
        return cls(
            arrival=int(row["arrival"]),
            release=row["release"],
            group=row["group"],
            receiver=row["receiver"],
            kind=ReleaseKind(row["kind"]),
        )


@dataclass(frozen=True)
class Handover:
    """一次摄入得到的全部交接事实（按 arrival 原样保留）。"""

    arrivals: tuple[int, ...]
    orders: tuple[OrderLine, ...]
    samples: tuple[Sample, ...]
    links: tuple[SamplingLink, ...]
    methods: tuple[Method, ...]
    results: tuple[TestResult, ...]
    dispatches: tuple[Dispatch, ...]
    releases: tuple[Release, ...]
    row_sources: dict[str, str] = field(default_factory=dict)
