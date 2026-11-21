"""领域枚举与状态机定义。"""

from enum import Enum


class SampleStatus(str, Enum):
    """实物份额的当前状态。"""

    AVAILABLE = "available"
    TAINTED = "tainted"

    @property
    def usable(self) -> bool:
        return self is SampleStatus.AVAILABLE


class ResultStatus(str, Enum):
    """检验结果状态。"""

    BELOW = "below"          # 低于检出限：给出可支持的区间而非零
    DETECTED = "detected"    # 定量结果
    RETRACTED = "retracted"  # 撤回：无结果证据


class DispatchState(str, Enum):
    """送检份额在场所侧的状态机。

    已安排送检的份额在场所确认撤销（cancel_ack）之前，
    不能又作为另一次检验的可用份额。
    """

    ALLOCATED = "allocated"
    RECEIVED = "received"
    CANCEL_REQUESTED = "cancel_requested"
    CANCEL_ACK = "cancel_ack"

    @property
    def holds_share(self) -> bool:
        """该状态是否仍占用实物份额。"""
        return self is not DispatchState.CANCEL_ACK


class EvidenceKind(str, Enum):
    """证据形态：四类不可互相替代的证据。"""

    QUANTITATIVE = "quantitative"        # 定量
    INTERVAL = "interval"                # 未检出（可支持区间）
    NO_RESULT = "no_result"              # 无结果（撤回/缺结果）
    SAMPLE_DESTROYED = "sample_destroyed"  # 样本破坏/污染
    METHOD_INAPPLICABLE = "method_inapplicable"  # 测法不适用


class ReleaseKind(str, Enum):
    """采购侧结论接收事实。"""

    OFFERED = "offered"                      # 已交付待签收
    ACCEPTED = "accepted"                    # 已签收入库
    CORRECTION_ACK = "correction_ack"        # 更正知悉
