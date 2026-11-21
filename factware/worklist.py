"""缺证工作清单：按缺证原因查寻还可补测的实物份额。"""

from dataclasses import dataclass

from factware.evaluation import (
    IndependenceLedger,
    MissingReason,
    _active_dispatch_holds,
    evaluate_groups,
)
from factware.lineage import ShareGraph
from factware.models import Handover, OrderLine


@dataclass(frozen=True)
class CandidateShare:
    """一份可用于补测的实物份额及其当前受限情况。"""

    sample: str
    remaining_grams: float
    roots: tuple[str, ...]
    matrix: str
    usable: bool
    blocker: str | None
    blocker_detail: str | None = None


@dataclass(frozen=True)
class WorkItem:
    """一条缺证订单行的补测指引。"""

    group: str
    line: OrderLine
    missing: tuple[MissingReason, ...]
    candidates: tuple[CandidateShare, ...]


def build_worklist(handover: Handover, graph: ShareGraph, as_of: int) -> tuple[WorkItem, ...]:
    """列出当前仍缺证的订单行，以及每行可补的实物份额。"""
    ledger = IndependenceLedger()
    verdicts = evaluate_groups(handover, graph, as_of, ledger)
    holds = _active_dispatch_holds(handover, as_of)
    items: list[WorkItem] = []

    for group in sorted(verdicts):
        verdict = verdicts[group]
        if verdict.compliant:
            continue
        for line_verdict in verdict.lines:
            if line_verdict.compliant:
                continue
            candidates: list[CandidateShare] = []
            for state in graph.usable_shares():
                if line_verdict.line.lot not in state.sample.source_lots:
                    continue
                matrix = graph.derive_matrix(state.sample.sample)
                roots = graph.roots(state.sample.sample)
                blocker = None
                detail = None
                if state.sample.sample in holds:
                    blocker = "dispatch_held"
                    detail = holds[state.sample.sample].value
                else:
                    reason = ledger.block_reason(state.sample.sample, graph, group)
                    if reason is not None:
                        blocker = "independence_consumed"
                        detail = reason.detail
                candidates.append(CandidateShare(
                    sample=state.sample.sample,
                    remaining_grams=state.remaining_grams,
                    roots=tuple(sorted(roots)),
                    matrix=matrix,
                    usable=blocker is None,
                    blocker=blocker,
                    blocker_detail=detail,
                ))
            items.append(WorkItem(
                group=group,
                line=line_verdict.line,
                missing=line_verdict.missing,
                candidates=tuple(candidates),
            ))
    return tuple(items)
