"""试样份额谱系：分取克数、污染传播、剩余克数与独立根。

同一混合来源不能充当独立同批样；已经用于某个独立资格的实物份额
与其派生物不得再次证明独立性（账本见 evaluation 模块）。
"""

from dataclasses import dataclass

from factware.enums import SampleStatus
from factware.models import Handover, Sample, SamplingLink


@dataclass(frozen=True)
class ShareState:
    """某一时刻一份份额的可用状态与剩余克数。"""

    sample: Sample
    remaining_grams: float
    tainted: bool
    tainted_by: str | None


class ShareGraph:
    """依据截至某 arrival 的份额、分取登记与批次基质映射构建的谱系快照。"""

    def __init__(
        self,
        handover: Handover,
        as_of_arrival: int,
        lot_matrix: dict[str, str],
    ) -> None:
        self._handover = handover
        self._as_of = as_of_arrival
        self._lot_matrix = dict(lot_matrix)
        self._latest: dict[str, Sample] = {}
        for sample in handover.samples:
            if sample.arrival <= as_of_arrival:
                self._latest[sample.sample] = sample
        self._links = [
            link for link in handover.links
            if link.child in self._latest and link.parent in self._latest
        ]
        self._children: dict[str, list[SamplingLink]] = {}
        self._parents: dict[str, list[SamplingLink]] = {}
        for link in self._links:
            self._children.setdefault(link.parent, []).append(link)
            self._parents.setdefault(link.child, []).append(link)
        self._states = {sample_id: self._build_state(sample_id) for sample_id in self._latest}

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._latest))

    def sample(self, sample_id: str) -> Sample:
        return self._latest[sample_id]

    def state(self, sample_id: str) -> ShareState:
        return self._states[sample_id]

    def roots(self, sample_id: str) -> frozenset[str]:
        """沿父样链向上得到的独立实物根集合。"""
        parents = self._parents.get(sample_id, ())
        if not parents:
            return frozenset({sample_id})
        roots: set[str] = set()
        for link in parents:
            roots.update(self.roots(link.parent))
        return frozenset(roots)

    def subtree(self, sample_id: str) -> frozenset[str]:
        """该份额及其全部派生物。"""
        members = {sample_id}
        for link in self._children.get(sample_id, ()):
            members.update(self.subtree(link.child))
        return frozenset(members)

    def derive_matrix(self, sample_id: str) -> str:
        """份额基质：根份额取批次基质；混合样取 mixed-<基质A>/<基质B> 记号。

        方法表用同一记号登记可适用的混合基质（如 mixed-PE）。
        """
        sample = self._latest[sample_id]
        root_matrices = sorted({
            self._root_matrix(root) for root in self.roots(sample_id)
        })
        if not sample.is_mixed and len(root_matrices) == 1:
            return root_matrices[0]
        if len(root_matrices) == 1 and sample.is_mixed:
            return f"mixed-{root_matrices[0]}"
        return "mixed-" + "/".join(root_matrices)

    def _root_matrix(self, root_id: str) -> str:
        sample = self._latest[root_id]
        matrices = {
            self._lot_matrix[lot]
            for lot in sample.source_lots
            if lot in self._lot_matrix
        }
        if len(matrices) == 1:
            return next(iter(matrices))
        if not matrices:
            raise KeyError(f"根份额 {root_id} 的来源批次没有订单基质映射")
        return "/".join(sorted(matrices))

    def _build_state(self, sample_id: str) -> ShareState:
        sample = self._latest[sample_id]
        tainted_roots = sorted(
            root for root in self.roots(sample_id)
            if self._latest[root].status is SampleStatus.TAINTED
        )
        tainted = bool(tainted_roots) or sample.status is SampleStatus.TAINTED
        tainted_by = tainted_roots[0] if tainted_roots else (
            sample.sample if sample.status is SampleStatus.TAINTED else None
        )
        remaining = self._remaining_grams(sample_id)
        return ShareState(
            sample=sample,
            remaining_grams=max(remaining, 0.0),
            tainted=tainted,
            tainted_by=tainted_by,
        )

    def _remaining_grams(self, sample_id: str) -> float:
        sample = self._latest[sample_id]
        withdrawn = sum(link.grams for link in self._children.get(sample_id, ()))
        return sample.grams - withdrawn

    def usable_shares(self) -> tuple[ShareState, ...]:
        """当前可作为检验实物来源的份额：未污染且尚有剩余克数。"""
        return tuple(
            state for sample_id, state in sorted(self._states.items())
            if not state.tainted and state.remaining_grams > 0
        )
