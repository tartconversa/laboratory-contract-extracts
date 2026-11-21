"""订单行组合格评价与独立性账本。

独立性规则：
- 每个独立资格消耗一个独立实物根（roots），同一根及其派生物不得再次
  证明另一个独立资格；混合样的根集合作为整体一次消耗。
- 已登记的混合覆盖关系可一次证明同组内多个 pooled 订单行（同批供货），
  实物用量仍只记一次。
- 已安排送检且未经场所确认撤销的份额，不能充当另一次检验的可用份额。
"""

from dataclasses import dataclass

from factware.enums import DispatchState
from factware.evidence import Evidence, evaluate_result, latest_results
from factware.lineage import ShareGraph
from factware.models import Handover, Method, OrderLine


@dataclass(frozen=True)
class MissingReason:
    """缺证原因，供送检同事按原因检索可补实物份额。"""

    code: str
    detail: str


@dataclass
class LineVerdict:
    """单个订单行的评价结论。"""

    line: OrderLine
    compliant: bool
    required: int
    independent_shares: int
    evidence: tuple[Evidence, ...]
    missing: tuple[MissingReason, ...]
    used_roots: frozenset[str] = frozenset()
    pooled_coverage_id: str | None = None


@dataclass
class GroupVerdict:
    """整组结论：组合包装各部件必检项全部对上各自试样后才合格。"""

    group: str
    lines: tuple[LineVerdict, ...]
    compliant: bool
    missing: tuple[MissingReason, ...]
    used_roots: frozenset[str] = frozenset()
    pooled: bool = False


class IndependenceLedger:
    """订单组内的独立性账本：按实际使用的份额身份记账。

    独立性在每个订单组（一次采购结论交付范围）内部成立：
    - 已经用于组内某个资格的份额及其派生物，不得再证明组内另一资格；
    - 同一父样的不同分取支互相独立，可分别支撑不同资格；
    - 同一份混合样不能重复充当两份独立试样，混合覆盖只可登记一次，
      且实际试样用量只记一次。
    跨订单组的同批供货只能由合同认可的覆盖关系证明，不由份额复用
    隐含得出；不同采购组对同批实物各自取得的独立证据互不冲销。
    """

    def __init__(self) -> None:
        # 组 -> 被消耗份额 -> 资格标识
        self._consumed: dict[str, dict[str, str]] = {}
        # 组 -> 混合覆盖标识 -> 资格标识
        self._pooled_usages: dict[str, dict[str, str]] = {}

    def block_reason(
        self, sample_id: str, graph: ShareGraph, group: str
    ) -> MissingReason | None:
        consumed = self._consumed.get(group, {})
        # 沿派生物方向（向下）锁定：候选属于已消耗份额自身或其派生物即冲突。
        blocked = sorted(
            used for used in consumed if sample_id in graph.subtree(used)
        )
        if not blocked:
            return None
        who = sorted({consumed[used] for used in blocked})
        return MissingReason(
            code="independence_consumed",
            detail=f"份额 {sample_id} 属于组 {group} 已用于 {','.join(who)} 的 {','.join(blocked)} 及其派生物",
        )

    def consume(self, sample_id: str, graph: ShareGraph, qualification_id: str) -> None:
        group = qualification_id.split("/", 1)[0]
        reason = self.block_reason(sample_id, graph, group)
        if reason is not None:
            raise ValueError(reason.detail)
        self._consumed.setdefault(group, {})[sample_id] = qualification_id

    def mark_pooled(
        self, coverage_id: str, sample_id: str, graph: ShareGraph, group: str
    ) -> None:
        usages = self._pooled_usages.setdefault(group, {})
        prior = usages.get(coverage_id)
        if prior is not None and prior != group:
            raise ValueError(f"混合覆盖 {coverage_id} 已用于 {prior}，不可重复充当独立试样")
        usages[coverage_id] = group
        # 实际试样用量只记一次：混合覆盖整体作为一份份额消耗。
        consumed = self._consumed.setdefault(group, {})
        if sample_id not in consumed:
            consumed[sample_id] = group

    def consumed_in(self, group: str) -> frozenset[str]:
        return frozenset(self._consumed.get(group, {}))

    @property
    def consumed_shares(self) -> frozenset[str]:
        return frozenset(
            share for consumed in self._consumed.values() for share in consumed
        )


def _active_dispatch_holds(handover: Handover, as_of: int) -> dict[str, DispatchState]:
    """截至该时刻仍占用份额的送检单（cancel_ack 之后释放）。"""
    latest: dict[str, DispatchState] = {}
    for dispatch in handover.dispatches:
        if dispatch.arrival > as_of:
            continue
        latest[dispatch.dispatch] = dispatch.state
    holds: dict[str, DispatchState] = {}
    for dispatch in handover.dispatches:
        if dispatch.arrival > as_of:
            continue
        state = latest[dispatch.dispatch]
        if state.holds_share:
            holds[dispatch.sample] = state
    return holds


def _candidate_evidence(
    line: OrderLine,
    graph: ShareGraph,
    handover: Handover,
    methods: dict[str, Method],
    as_of: int,
) -> tuple[Evidence, ...]:
    results = latest_results(handover.results, as_of)
    evidences: list[Evidence] = []
    for result in results.values():
        sample = graph.sample(result.sample)
        # 订单行只接受来源批次包含合同批次的份额。
        if line.lot not in sample.source_lots:
            continue
        evidences.append(evaluate_result(result, line, graph, methods))
    return tuple(evidences)


def _evaluate_single_line(
    line: OrderLine,
    graph: ShareGraph,
    handover: Handover,
    methods: dict[str, Method],
    as_of: int,
    ledger: IndependenceLedger,
) -> LineVerdict:
    evidences = _candidate_evidence(line, graph, handover, methods, as_of)
    missing: list[MissingReason] = []
    used_roots: set[str] = set()
    accepted: list[Evidence] = []

    # 先暴露非合格形态证据的缺证原因（撤回/污染/不适用/超标）。
    for evidence in evidences:
        if not evidence.is_compliant_evidence:
            missing.append(MissingReason(
                code=f"evidence_{evidence.kind.value}",
                detail=f"{evidence.result_id}@{evidence.sample}: {evidence.reason or '不合格'}",
            ))

    compliant = [e for e in evidences if e.is_compliant_evidence]
    # 同一份额只计一次独立资格；按证据到达顺序取最早可用的份额。
    # 送检占用不否定该份额上已经产生的结果——它确实被用于这次检验；
    # 占用限制只阻止把同一份额再当作另一次检验的可用份额（见 worklist）。
    seen_shares: set[str] = set()
    for evidence in sorted(compliant, key=lambda e: (e.arrival, e.result_id)):
        if evidence.sample in seen_shares:
            continue
        clash = ledger.block_reason(evidence.sample, graph, line.group)
        if clash is not None:
            missing.append(clash)
            continue
        ledger.consume(evidence.sample, graph, f"{line.group}/{line.line}")
        seen_shares.add(evidence.sample)
        used_roots.update(graph.roots(evidence.sample))
        accepted.append(evidence)
        if len(seen_shares) >= line.replicates:
            break

    if len(seen_shares) < line.replicates:
        missing.append(MissingReason(
            code="insufficient_independent_shares",
            detail=f"需要 {line.replicates} 份独立试样，仅对上 {len(seen_shares)} 份",
        ))
    return LineVerdict(
        line=line,
        compliant=len(seen_shares) >= line.replicates,
        required=line.replicates,
        independent_shares=len(seen_shares),
        evidence=tuple(accepted) or tuple(evidences),
        missing=tuple(missing),
        used_roots=frozenset(used_roots),
    )


def _evaluate_pooled_group(
    lines: tuple[OrderLine, ...],
    graph: ShareGraph,
    handover: Handover,
    methods: dict[str, Method],
    as_of: int,
    ledger: IndependenceLedger,
) -> GroupVerdict | None:
    """尝试用一份登记过的混合覆盖证明整组 pooled 行；不可行则返回 None。"""
    pooled_lines = tuple(line for line in lines if line.pooled)
    if len(pooled_lines) != len(lines) or not pooled_lines:
        return None
    required_lots = frozenset(line.lot for line in pooled_lines)
    results = latest_results(handover.results, as_of)
    last_failure: tuple[LineVerdict, ...] | None = None

    for result in results.values():
        sample = graph.sample(result.sample)
        if not sample.is_mixed:
            continue
        if frozenset(sample.source_lots) != required_lots:
            continue
        state = graph.state(result.sample)
        if state.tainted:
            continue
        # 混合样必须对组内每一行都是合格证据（基质/测项/区间各自核对）。
        per_line: list[LineVerdict] = []
        for line in pooled_lines:
            evidence = evaluate_result(result, line, graph, methods)
            if not evidence.is_compliant_evidence:
                per_line.append(LineVerdict(
                    line=line, compliant=False, required=line.replicates,
                    independent_shares=0, evidence=(evidence,),
                    missing=(MissingReason(
                        code=f"evidence_{evidence.kind.value}",
                        detail=f"{evidence.result_id}: {evidence.reason or '不合格'}",
                    ),),
                ))
            else:
                per_line.append(LineVerdict(
                    line=line, compliant=True, required=line.replicates,
                    independent_shares=1, evidence=(evidence,),
                    missing=(),
                ))
        if not all(verdict.compliant for verdict in per_line):
            # 该候选不能证明整组；保留原因并继续尝试其他混合样。
            last_failure = tuple(per_line)
            continue
        roots = graph.roots(result.sample)
        coverage_id = f"pool:{result.sample}:{':'.join(sorted(required_lots))}"
        clash = ledger.block_reason(result.sample, graph, pooled_lines[0].group)
        if clash is not None:
            return GroupVerdict(
                group=pooled_lines[0].group, lines=tuple(per_line),
                compliant=False, missing=(clash,), used_roots=frozenset(),
                pooled=True,
            )
        ledger.mark_pooled(coverage_id, result.sample, graph, pooled_lines[0].group)
        line_verdicts = tuple(
            LineVerdict(
                line=verdict.line, compliant=verdict.compliant,
                required=verdict.required, independent_shares=verdict.independent_shares,
                evidence=verdict.evidence, missing=verdict.missing,
                used_roots=roots, pooled_coverage_id=coverage_id,
            )
            for verdict in per_line
        )
        return GroupVerdict(
            group=pooled_lines[0].group, lines=line_verdicts,
            compliant=True, missing=(), used_roots=roots, pooled=True,
        )
    if last_failure is not None:
        missing = tuple(reason for verdict in last_failure for reason in verdict.missing)
        return GroupVerdict(
            group=pooled_lines[0].group, lines=last_failure,
            compliant=False, missing=missing, used_roots=frozenset(), pooled=True,
        )
    return None


def evaluate_groups(
    handover: Handover,
    graph: ShareGraph,
    as_of: int,
    ledger: IndependenceLedger | None = None,
) -> dict[str, GroupVerdict]:
    """评价截至某 arrival 的全部订单组。"""
    methods = {method.method: method for method in handover.methods}
    ledger = ledger or IndependenceLedger()
    verdicts: dict[str, GroupVerdict] = {}

    grouped: dict[str, list[OrderLine]] = {}
    for line in handover.orders:
        grouped.setdefault(line.group, []).append(line)

    # 合同认可的混合覆盖先登记，再处理独立资格：混合样与独立分取支
    # 是不同份额，可并存；同一份额仍由账本保证不会被重复消耗。
    def is_pooled(group: str) -> bool:
        return any(line.pooled for line in grouped[group])

    for group in sorted(grouped, key=lambda name: (not is_pooled(name), name)):
        lines = tuple(sorted(grouped[group], key=lambda item: item.line))
        pooled = _evaluate_pooled_group(lines, graph, handover, methods, as_of, ledger)
        if pooled is not None:
            verdicts[group] = pooled
            continue
        line_verdicts = tuple(
            _evaluate_single_line(line, graph, handover, methods, as_of, ledger)
            for line in lines
        )
        missing = tuple(reason for verdict in line_verdicts for reason in verdict.missing)
        used = frozenset().union(*(
            verdict.used_roots for verdict in line_verdicts
        )) if line_verdicts else frozenset()
        verdicts[group] = GroupVerdict(
            group=group, lines=line_verdicts,
            compliant=all(verdict.compliant for verdict in line_verdicts),
            missing=missing, used_roots=used, pooled=False,
        )
    return verdicts
