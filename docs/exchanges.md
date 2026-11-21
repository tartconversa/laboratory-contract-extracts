# 交接资料说明

材料为合成包装样品。 `orders.csv` 的 `group` 是一次结论交付范围，`matrix` 是基质，`replicates` 是独立试样份数，`upper` 含上限。`samples.csv` 以 `source_lots` 和 `parent` 表示分取谱系，共用同一个混合来源不能充当独立同批样。数量单位克。 `methods.csv` 的 `factor` 转换到合同单位。 `test_results.csv` 中 `below` 表示结果低于给出的检出限，`detected` 为定量，`retracted` 表示结果撤回。`method` 也决定适用基质，且只可在报告日期有效时用于合同。 `dispatch.csv` 与 `release.csv` 是已存在的送检和结论接收事实。样品混合来源需保存分取量及父样。允许用混合结论覆盖多行的采购组须明确登记相同订单组和涉及尾批，实际试样用量仍只记一次。已经用于某个独立资格的实物份额与其派生物不得再次证明独立性。

字段 `arrival` 为合成交接批号，同号记录属于同次接收。没有批号的文件为该批资料采用的固定目录。

- `orders.csv`
- `samples.csv`
- `methods.csv`
- `test_results.csv`
- `dispatch.csv`
- `release.csv`
- `sampling.csv`
