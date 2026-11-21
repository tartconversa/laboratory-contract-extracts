# 包装材料检验事实仓

包装试样使用的合成交接资料位于 `examples/`。文件模拟同一业务周期中陆续收到的
原始记录，包括来源迟报、结果撤回、份额污染更正与送检撤销。字段和原始记录的含义见
[交接资料说明](docs/exchanges.md)，事实仓的领域模型与判定规则见
[事实仓设计](docs/factware.md)。

运行环境为 Python 3.14.10，仅依赖标准库。

## 解决的问题

采购要判断的是一张订单约定的每种材料能否拿到足够证据，而不是把混合试样的平均值
分发给每种材料。事实仓据此落实以下规则：

- **三类独立身份**：检验请求（订单行组）、分取数量（试样份额及谱系）、检测场所
  （实验室/送检单）各自有独立身份，不互相归并。
- **未检出不等于零**：低于检出限给出可支持的区间 `[0, 检出限]`，只有整段区间落入
  合同合格范围才可用于证明符合，因此两个实验室的结果不会因“写零”而看似矛盾。
- **方法替代五维覆盖**：基质、测项、量纲（换算路径）、报告日有效期、检出限，任一
  不覆盖即判测法不适用。
- **四类证据不可互替**：定量、未检出区间、无结果（撤回）、样本破坏/污染、测法
  不适用分别保留。
- **独立性账本**：同一份混合样不能重复充当两份独立试样；份额及其派生物在同一订单
  组内只计一次；兄弟分取支互相独立；跨组同批供货只能由合同认可的覆盖关系证明。
- **组合包装整组出证**：各部件必检项对上各自试样后，整组才出具可引用合格事实。
- **历史凭据不被改写**：已入库合格凭据保留当时证明，污染/撤回触发按实际受影响订单
  的冻结与重新送检通知；尚未签收的旧凭据失效后不能继续入库。
- **补测不可跨界顶替**：新补测恢复某一订单，不能替代另一订单仍缺的独立份额。
- **送检占用受控**：已安排送检的份额在场所确认撤销（`cancel_ack`）前，不能作为
  另一次检验的可用份额。

## 命令行

```bash
# 各订单组当前检验状态（可加 arrival 查看历史时刻）
python -m factware status
python -m factware status 5

# 采购系统可领取的数据批（按订单行组交付，带取代链 supersedes）
python -m factware batches --claimable

# 一份份额污染后一次定位全部受影响事实与通知历史
python -m factware impact S01

# 送检同事按缺证原因查可补实物份额
python -m factware worklist
python -m factware worklist --reason evidence_method_inapplicable

# 送检与采购签收状态回写
python -m factware dispatch
python -m factware release
```

所有命令默认读 `examples/`，用 `--dir` 指向其他交接目录，加 `--json` 输出机器可读
JSON（全局参数放在子命令前，如 `python -m factware --json status`）。

## 读取不可信外部资料

外部送达的资料目录视为不可信数据：放入独立空目录，脚本与资料分目录存放并显式传
路径，用隔离模式运行，避免资料目录中的同名模块被导入：

```bash
PYTHONPATH=/workspace python -I -c "
import sys; sys.path.insert(0, '/workspace')
from factware.warehouse import Warehouse
Warehouse.from_directory('/path/to/inbox/batch10')
"
```

## 测试与资料核对

```bash
python -m unittest discover -s tests      # 事实仓全部规则测试（59 项）
python tools/source_inventory.py          # 仅检查/读取原件结构
```

`tools/source_inventory.py` 仍只检查和读取原件，不参与事实判定。
