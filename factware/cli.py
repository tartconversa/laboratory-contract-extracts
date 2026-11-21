"""事实仓命令行：供采购系统与送检同事查询和回写状态。"""

import argparse
import json
from dataclasses import asdict

from factware.ingest import HandoverError
from factware.warehouse import Warehouse


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return
    print(_render_text(payload))


def _json_default(value):
    if hasattr(value, "__dict__"):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, frozenset):
        return sorted(value)
    raise TypeError(f"无法序列化：{type(value)}")


def _render_text(payload: dict) -> str:
    lines: list[str] = []

    def walk(node, indent: int) -> None:
        pad = "  " * indent
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list, tuple)):
                    lines.append(f"{pad}{key}:")
                    walk(value, indent + 1)
                else:
                    lines.append(f"{pad}{key}: {value}")
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    walk(item, indent)
                    lines.append("")
                else:
                    lines.append(f"{pad}- {item}")
        else:
            lines.append(f"{pad}{node}")

    walk(payload, 0)
    return "\n".join(line for line in lines if line.strip())


def _status_payload(snapshot) -> dict:
    return {
        "arrival": snapshot.arrival,
        "groups": [asdict(status) for status in snapshot.groups.values()],
        "notifications": [asdict(item) for item in snapshot.notifications],
    }


def _cmd_status(warehouse: Warehouse, args) -> None:
    snapshot = warehouse.snapshot(int(args.arrival)) if args.arrival else warehouse.latest()
    _emit(_status_payload(snapshot), args.json)


def _cmd_batches(warehouse: Warehouse, args) -> None:
    if args.claimable:
        batches = warehouse.claimable_batches()
    else:
        batches = warehouse.latest().outbox
    _emit({"batches": [asdict(batch) for batch in batches]}, args.json)


def _cmd_impact(warehouse: Warehouse, args) -> None:
    _emit(warehouse.impact(args.sample), args.json)


def _cmd_worklist(warehouse: Warehouse, args) -> None:
    snapshot = warehouse.latest()
    items = [
        {
            "group": item.group,
            "line": item.line.line,
            "lot": item.line.lot,
            "missing": [asdict(reason) for reason in item.missing],
            "candidates": [asdict(candidate) for candidate in item.candidates],
        }
        for item in snapshot.worklist
        if args.reason is None or any(reason.code == args.reason for reason in item.missing)
    ]
    _emit({"arrival": snapshot.arrival, "worklist": items}, args.json)


def _cmd_dispatch(warehouse: Warehouse, args) -> None:
    rows = [
        {
            "arrival": item.arrival, "dispatch": item.dispatch, "sample": item.sample,
            "lab": item.lab, "grams": item.grams, "state": item.state.value,
            "holds_share": item.state.holds_share,
        }
        for item in warehouse.handover.dispatches
    ]
    _emit({"dispatch": rows}, args.json)


def _cmd_release(warehouse: Warehouse, args) -> None:
    rows = [
        {
            "arrival": item.arrival, "release": item.release, "group": item.group,
            "receiver": item.receiver, "kind": item.kind.value,
        }
        for item in warehouse.handover.releases
    ]
    _emit({"release": rows}, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="包装材料检验事实仓")
    parser.add_argument("--dir", default="examples", help="交接资料目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="查看某时刻（默认最新）各组检验状态")
    status.add_argument("arrival", nargs="?", default=None)
    status.set_defaults(func=_cmd_status)

    batches = sub.add_parser("batches", help="查看采购可领取/全部交付数据批")
    batches.add_argument("--claimable", action="store_true")
    batches.set_defaults(func=_cmd_batches)

    impact = sub.add_parser("impact", help="按份额级联定位全部受影响事实")
    impact.add_argument("sample")
    impact.set_defaults(func=_cmd_impact)

    worklist = sub.add_parser("worklist", help="按缺证原因查可补实物份额")
    worklist.add_argument("--reason", default=None)
    worklist.set_defaults(func=_cmd_worklist)

    dispatch = sub.add_parser("dispatch", help="查看送检与场所状态回写事实")
    dispatch.set_defaults(func=_cmd_dispatch)

    release = sub.add_parser("release", help="查看采购签收状态回写事实")
    release.set_defaults(func=_cmd_release)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        warehouse = Warehouse.from_directory(args.dir)
    except HandoverError as error:
        parser.exit(2, f"交接资料错误：{error}\n")
    args.func(warehouse, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
