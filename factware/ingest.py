"""交接资料摄入：读取陆续到达的 CSV/TSV/JSONL 原件并做身份校验。

只读取原件，不修改输入目录；迟到记录与冲突记录都保留，
由仓库按 arrival 重放决定某一时刻哪些事实生效。
"""

import csv
import json
from pathlib import Path

from factware.enums import (
    DispatchState,
    ReleaseKind,
    ResultStatus,
    SampleStatus,
)
from factware.models import (
    Dispatch,
    Handover,
    Method,
    OrderLine,
    Release,
    SamplingLink,
    Sample,
    TestResult,
)


class HandoverError(ValueError):
    """交接原件结构或引用关系不合法。"""


_FILES = (
    "orders.csv",
    "samples.csv",
    "methods.csv",
    "test_results.csv",
    "dispatch.csv",
    "release.csv",
    "sampling.csv",
)


def read_records(path: Path) -> list[dict]:
    """读取一个交接文件中的原始记录。"""
    with path.open(encoding="utf-8", newline="") as stream:
        if path.suffix == ".jsonl":
            records = [json.loads(line) for line in stream if line.strip()]
        else:
            delimiter = "\t" if path.suffix == ".tsv" else ","
            reader = csv.DictReader(stream, delimiter=delimiter)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise HandoverError(f"文件表头无效：{path.name}")
            records = list(reader)
    for record in records:
        if not isinstance(record, dict) or any(value is None for value in record.values()):
            raise HandoverError(f"记录列数与表头不符：{path.name}")
    return records


def _require_columns(name: str, rows: list[dict], required: set[str]) -> None:
    present = {key for row in rows for key in row}
    missing = required - present
    if missing:
        raise HandoverError(f"{name} 缺少字段：{sorted(missing)}")


def load_handover(root: str | Path) -> Handover:
    """从交接目录载入事实并校验身份、枚举与引用完整性。"""
    root = Path(root)
    if not root.is_dir():
        raise HandoverError(f"交接目录不存在：{root}")

    tables: dict[str, list[dict]] = {}
    for name in _FILES:
        path = root / name
        if not path.exists():
            raise HandoverError(f"缺少交接文件：{name}")
        tables[name] = read_records(path)

    orders = [_parse_order(row) for row in tables["orders.csv"]]
    samples = [Sample.from_row(row) for row in tables["samples.csv"]]
    methods = [Method.from_row(row) for row in tables["methods.csv"]]
    results = [TestResult.from_row(row) for row in tables["test_results.csv"]]
    dispatches = [Dispatch.from_row(row) for row in tables["dispatch.csv"]]
    releases = [Release.from_row(row) for row in tables["release.csv"]]
    links = [
        SamplingLink(child=row["child"], parent=row["parent"], grams=float(row["grams"]))
        for row in tables["sampling.csv"]
    ]

    _validate_enums(tables)
    _validate_identities(orders, samples, methods, results, dispatches, releases, links)
    _validate_revisions(results)

    arrivals = tuple(sorted({
        *[s.arrival for s in samples],
        *[r.arrival for r in results],
        *[d.arrival for d in dispatches],
        *[x.arrival for x in releases],
    }))
    row_sources = {name: str(root / name) for name in tables}
    return Handover(
        arrivals=arrivals,
        orders=tuple(orders),
        samples=tuple(samples),
        links=tuple(links),
        methods=tuple(methods),
        results=tuple(results),
        dispatches=tuple(dispatches),
        releases=tuple(releases),
        row_sources=row_sources,
    )


def _parse_order(row: dict) -> OrderLine:
    pooled = row["pooled"].strip().lower()
    if pooled not in {"yes", "no"}:
        raise HandoverError(f"orders.csv 的 pooled 取值非法：{row['pooled']}")
    return OrderLine(
        group=row["group"],
        line=row["line"],
        material=row["material"],
        lot=row["lot"],
        matrix=row["matrix"],
        metric=row["metric"],
        unit=row["unit"],
        upper=float(row["upper"]),
        replicates=int(row["replicates"]),
        pooled=pooled == "yes",
    )


def _validate_enums(tables: dict[str, list[dict]]) -> None:
    for row in tables["samples.csv"]:
        SampleStatus(row["status"])
    for row in tables["test_results.csv"]:
        ResultStatus(row["status"])
    for row in tables["dispatch.csv"]:
        DispatchState(row["state"])
    for row in tables["release.csv"]:
        ReleaseKind(row["kind"])


def _validate_identities(orders, samples, methods, results, dispatches, releases, links) -> None:
    sample_ids = {s.sample for s in samples}
    method_ids = {m.method for m in methods}
    groups = {o.group for o in orders}

    order_keys = [(o.group, o.line) for o in orders]
    if len(set(order_keys)) != len(order_keys):
        raise HandoverError("订单行身份 (group, line) 重复")
    if len(sample_ids) != len(samples):
        # 同名份额只允许因状态更正而再次出现（如 available→tainted）。
        seen: dict[str, str] = {}
        for sample in samples:
            if sample.sample in seen and seen[sample.sample] == sample.status.value:
                raise HandoverError(f"试样份额身份重复且无状态更正：{sample.sample}")
            seen[sample.sample] = sample.status.value

    for link in links:
        if link.child not in sample_ids or link.parent not in sample_ids:
            raise HandoverError(f"分取登记引用未知份额：{link.child}->{link.parent}")
        if link.grams <= 0:
            raise HandoverError(f"分取克数必须为正：{link.child}->{link.parent}")
    for sample in samples:
        unknown_parents = set(sample.parents) - sample_ids
        if unknown_parents:
            raise HandoverError(f"份额 {sample.sample} 的父样未登记：{sorted(unknown_parents)}")
        if sample.grams <= 0:
            raise HandoverError(f"份额克数必须为正：{sample.sample}")
    for result in results:
        if result.sample not in sample_ids:
            raise HandoverError(f"结果 {result.result} 引用未知份额：{result.sample}")
        if result.method not in method_ids:
            raise HandoverError(f"结果 {result.result} 引用未知方法：{result.method}")
    for dispatch in dispatches:
        if dispatch.sample not in sample_ids:
            raise HandoverError(f"送检单 {dispatch.dispatch} 引用未知份额：{dispatch.sample}")
        if dispatch.grams <= 0:
            raise HandoverError(f"送检克数必须为正：{dispatch.dispatch}")
    for release in releases:
        if release.group not in groups:
            raise HandoverError(f"签收事实引用未知订单组：{release.group}")


def _validate_revisions(results: list[TestResult]) -> None:
    seen: dict[str, int] = {}
    for result in results:
        prior = seen.get(result.result)
        if prior is not None and result.revision <= prior:
            raise HandoverError(
                f"结果 {result.result} 修订号须严格递增：{prior}->{result.revision}"
            )
        seen[result.result] = result.revision
