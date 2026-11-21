"""包装材料检验事实仓。

围绕采购订单行组、实物试样份额、检测场所三类独立身份，
保留检验事实的完整追溯链，并据此出具可引用的合格事实。
"""

from factware.warehouse import Warehouse

__all__ = ["Warehouse"]
