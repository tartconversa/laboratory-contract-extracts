"""检验事实仓：按 arrival 重放全部交接事实，保留追溯链。

仓库只追加、不改写历史：
- 已入库（accepted）的合格凭据保留当时的证明，另发冻结/重检通知；
- 尚未确认收货（仅 offered）的，旧凭据失效后不能继续用于入库；
- 每次采购结论与当前检验状态都可沿快照与证据链回溯。
"""

from dataclasses import dataclass, field

from factware.enums import ReleaseKind
from factware.evaluation import GroupVerdict, IndependenceLedger, evaluate_groups
from factware.ingest import load_handover
from factware.lineage import ShareGraph
from factware.models import Handover
from factware.worklist import WorkItem, build_worklist


@dataclass(frozen=True)
class EvidenceRef:
    """合格事实引用的证据指针。"""

    result: str
    revision: int
    sample: str
    method: str
    kind: str
    interval: tuple[float, float] | None
    report_date: str


@dataclass(frozen=True)
class GroupStatus:
    """一个订单组在某时刻的可引用状态。"""

    group: str
    compliant: bool
    pooled: bool
    lines: tuple[dict, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    missing_codes: tuple[str, ...]
    used_roots: tuple[str, ...]


@dataclass(frozen=True)
class Notification:
    """污染/撤回引发的影响通知。"""

    arrival: int
    group: str
    kind: str  # freeze_recheck | offer_invalidated
    affected_roots: tuple[str, ...]
    accepted_release: str | None
    detail: str


@dataclass(frozen=True)
class OutboxBatch:
    """采购系统可领取的一次数据批（按承诺的订单行组交付）。"""

    batch_id: str
    arrival: int
    group: str
    status: GroupStatus
    claimable: bool
    release: str | None
    release_kind: str | None
    notifications: tuple[Notification, ...]
    supersedes: tuple[str, ...]


@dataclass(frozen=True)
class Snapshot:
    """某一 arrival 时刻的完整事实仓快照。"""

    arrival: int
    groups: dict[str, GroupStatus]
    notifications: tuple[Notification, ...]
    outbox: tuple[OutboxBatch, ...]
    worklist: tuple[WorkItem, ...]


@dataclass
class _GroupMemory:
    accepted_release: str | None = None
    offered_release: str | None = None
    frozen: bool = False
    ever_compliant: bool = False
    last_batch: str | None = None
    last_compliant: bool | None = None
    batches_emitted: list[str] = field(default_factory=list)


class Warehouse:
    """事实仓：摄入交接目录并提供逐时刻快照与查询。"""

    def __init__(self, handover: Handover) -> None:
        self.handover = handover
        self._lot_matrix = {
            line.lot: line.matrix for line in handover.orders
        }
        self._memories: dict[str, _GroupMemory] = {
            line.group: _GroupMemory() for line in handover.orders
        }
        self._snapshots: dict[int, Snapshot] = {}
        self._all_notifications: list[Notification] = []
        self._replay()

    @classmethod
    def from_directory(cls, root: str) -> "Warehouse":
        return cls(load_handover(root))

    @property
    def arrivals(self) -> tuple[int, ...]:
        return self.handover.arrivals

    def snapshot(self, arrival: int | None = None) -> Snapshot:
        if arrival is None:
            arrival = self.handover.arrivals[-1]
        if arrival not in self._snapshots:
            raise KeyError(f"没有 arrival={arrival} 的快照")
        return self._snapshots[arrival]

    def latest(self) -> Snapshot:
        return self.snapshot(self.handover.arrivals[-1])

    # ---- 重放 -------------------------------------------------------

    def _replay(self) -> None:
        prior_arrival = None
        for arrival in self.handover.arrivals:
            self._snapshots[arrival] = self._build_snapshot(arrival, prior_arrival)
            prior_arrival = arrival

    def _build_snapshot(self, arrival: int, prior_arrival: int | None) -> Snapshot:
        graph = ShareGraph(self.handover, arrival, self._lot_matrix)
        ledger = IndependenceLedger()
        verdicts = evaluate_groups(self.handover, graph, arrival, ledger)
        prior = self._snapshots[prior_arrival] if prior_arrival is not None else None

        self._apply_releases(arrival)
        new_notifications = self._detect_notifications(arrival, verdicts, prior)
        self._all_notifications.extend(new_notifications)
        # 补测恢复合格后解除后续批次冻结；已入库凭据仍以历史快照保留。
        for group, verdict in verdicts.items():
            if verdict.compliant:
                self._memories[group].frozen = False
                self._memories[group].ever_compliant = True
        notifications = tuple(
            notice for notice in self._all_notifications if notice.arrival <= arrival
        )
        statuses = {group: self._to_status(verdict) for group, verdict in verdicts.items()}
        outbox = self._build_outbox(arrival, statuses, new_notifications, verdicts, prior)
        worklist = build_worklist(self.handover, graph, arrival)
        return Snapshot(
            arrival=arrival,
            groups=statuses,
            notifications=notifications,
            outbox=outbox,
            worklist=worklist,
        )

    def _apply_releases(self, arrival: int) -> None:
        for release in self.handover.releases:
            if release.arrival != arrival:
                continue
            memory = self._memories[release.group]
            if release.kind is ReleaseKind.ACCEPTED:
                memory.accepted_release = release.release
                memory.offered_release = None
                memory.frozen = False
            elif release.kind is ReleaseKind.OFFERED:
                memory.offered_release = release.release
            elif release.kind is ReleaseKind.CORRECTION_ACK:
                # 采购已知悉更正；冻结状态保持，直到重新合格。
                memory.accepted_release = memory.accepted_release or release.release

    def _detect_notifications(
        self,
        arrival: int,
        verdicts: dict[str, GroupVerdict],
        prior: Snapshot | None,
    ) -> tuple[Notification, ...]:
        if prior is None:
            return ()
        notifications: list[Notification] = []
        for group, verdict in verdicts.items():
            previous = prior.groups.get(group)
            # 仅在“上一时刻合格、此刻缺证”时发通知；先前就缺证不重复报。
            if previous is None or not previous.compliant or verdict.compliant:
                continue
            # 定位本次失效涉及的独立根（上一快照用过、此刻不再支撑的根）。
            affected = tuple(sorted(
                set(previous.used_roots) - set(verdict.used_roots)
            )) or tuple(sorted(previous.used_roots))
            memory = self._memories[group]
            if memory.accepted_release:
                memory.frozen = True
                notifications.append(Notification(
                    arrival=arrival, group=group, kind="freeze_recheck",
                    affected_roots=affected,
                    accepted_release=memory.accepted_release,
                    detail="已入库凭据保留当时证明；冻结后续批次并重新送检",
                ))
            else:
                notifications.append(Notification(
                    arrival=arrival, group=group, kind="offer_invalidated",
                    affected_roots=affected, accepted_release=None,
                    detail="尚未确认收货，旧合格凭据不得继续用于入库",
                ))
        return tuple(notifications)

    def _to_status(self, verdict: GroupVerdict) -> GroupStatus:
        line_payload = tuple(
            {
                "line": item.line.line,
                "material": item.line.material,
                "lot": item.line.lot,
                "required_replicates": item.required,
                "independent_shares": item.independent_shares,
                "compliant": item.compliant,
                "missing": [reason.code for reason in item.missing],
                "pooled_coverage": item.pooled_coverage_id,
            }
            for item in verdict.lines
        )
        refs: list[EvidenceRef] = []
        missing: list[str] = []
        for item in verdict.lines:
            for evidence in item.evidence:
                refs.append(EvidenceRef(
                    result=evidence.result_id,
                    revision=evidence.revision,
                    sample=evidence.sample,
                    method=evidence.method,
                    kind=evidence.kind.value,
                    interval=(evidence.interval.lower, evidence.interval.upper)
                    if evidence.interval else None,
                    report_date=evidence.report_date,
                ))
            missing.extend(reason.code for reason in item.missing)
        return GroupStatus(
            group=verdict.group,
            compliant=verdict.compliant,
            pooled=verdict.pooled,
            lines=line_payload,
            evidence_refs=tuple(refs),
            missing_codes=tuple(dict.fromkeys(missing)),
            used_roots=tuple(sorted(verdict.used_roots)),
        )

    def _build_outbox(
        self,
        arrival: int,
        statuses: dict[str, GroupStatus],
        new_notifications: tuple[Notification, ...],
        verdicts: dict[str, GroupVerdict],
        prior: Snapshot | None,
    ) -> tuple[OutboxBatch, ...]:
        batches: list[OutboxBatch] = []
        notices_by_group: dict[str, list[Notification]] = {}
        for notice in new_notifications:
            notices_by_group.setdefault(notice.group, []).append(notice)

        for group, status in statuses.items():
            memory = self._memories[group]
            previous = prior.groups.get(group) if prior else None
            flipped = previous is not None and previous.compliant != status.compliant
            new_release = any(
                release.arrival == arrival and release.group == group
                for release in self.handover.releases
            )
            # 从未合格且无签收事实的组没有可交付内容，不发批。
            if not (flipped or new_release):
                continue
            if not (memory.ever_compliant or new_release):
                continue
            batch_id = f"B{arrival:02d}-{group}"
            release = memory.accepted_release or memory.offered_release
            release_kind = None
            if memory.accepted_release:
                release_kind = ReleaseKind.ACCEPTED.value
            elif memory.offered_release:
                release_kind = ReleaseKind.OFFERED.value
            # 可领取只看当前是否合格：冻结/未签收失效的旧凭据不得继续用于入库；
            # 已入库凭据仍原样保留在历史批中，不被改写。
            batches.append(OutboxBatch(
                batch_id=batch_id, arrival=arrival, group=group, status=status,
                claimable=status.compliant, release=release, release_kind=release_kind,
                notifications=tuple(notices_by_group.get(group, ())),
                supersedes=tuple(memory.batches_emitted),
            ))
            memory.last_batch = batch_id
            memory.last_compliant = status.compliant
            memory.batches_emitted.append(batch_id)
        return tuple(batches)

    # ---- 查询 -------------------------------------------------------

    def impact(self, sample_id: str) -> dict:
        """一次定位某份额污染后所有受影响的订单事实（级联查询）。"""
        latest = self.latest()
        graph = ShareGraph(self.handover, latest.arrival, self._lot_matrix)
        tainted_roots = graph.roots(sample_id)
        affected_groups: list[dict] = []
        for group, status in latest.groups.items():
            if set(status.used_roots) & tainted_roots or self._group_touches_roots(group, tainted_roots):
                memory = self._memories[group]
                affected_groups.append({
                    "group": group,
                    "compliant": status.compliant,
                    "frozen": memory.frozen,
                    "accepted_release": memory.accepted_release,
                    "used_roots": list(status.used_roots),
                })
        history: dict[int, list[str]] = {}
        for snapshot in (self.snapshot(a) for a in self.arrivals):
            for notice in snapshot.notifications:
                if set(notice.affected_roots) & tainted_roots:
                    bucket = history.setdefault(notice.arrival, [])
                    if notice.detail not in bucket:
                        bucket.append(notice.detail)
        return {
            "sample": sample_id,
            "roots": sorted(tainted_roots),
            "subtree": sorted(graph.subtree(sample_id)),
            "affected_groups": affected_groups,
            "notification_history": [
                {"arrival": arrival, "notifications": details}
                for arrival, details in sorted(history.items())
            ],
        }

    def _group_touches_roots(self, group: str, roots: frozenset[str]) -> bool:
        for snapshot in (self.snapshot(a) for a in self.arrivals):
            status = snapshot.groups.get(group)
            if status and set(status.used_roots) & roots:
                return True
        return False

    def claimable_batches(self) -> tuple[OutboxBatch, ...]:
        """采购系统当前可领取的数据批。"""
        return tuple(batch for batch in self.latest().outbox if batch.claimable)
