"""Versioned database-only patches / 有版本检查的系统元数据修改。"""

import json

from common import call, connect, parser, require_execution_key, run, show


async def main() -> None:
    arguments = parser(
        "Update system metadata without touching files / 更新系统记录，不改文件"
    )
    arguments.add_argument(
        "--target-type", choices=["book", "resource", "source_node"], required=True
    )
    arguments.add_argument("--target-id", required=True)
    arguments.add_argument("--mode", choices=["patch", "fill_missing"], default="patch")
    arguments.add_argument("--set", action="append", default=[], metavar="FIELD=JSON")
    arguments.add_argument("--clear", action="append", default=[])
    arguments.add_argument("--override", action="append", default=[])
    arguments.add_argument(
        "--expected-revision",
        help="Original revision for an exact retry / 原请求的版本标识",
    )
    args = arguments.parse_args()
    require_execution_key(args)
    values = {}
    for assignment in args.set:
        name, separator, value = assignment.partition("=")
        if not separator or not name or name in values:
            raise ValueError(
                "Use unique FIELD=JSON entries / 字段必须唯一，值使用 JSON"
            )
        values[name] = json.loads(value)
    if not values and not args.clear:
        raise ValueError("Select fields to update or clear / 请明确更新或清空的字段")
    async with connect() as client:
        schema = await call(
            client,
            "get_metadata_schema",
            {"target_type": args.target_type, "target_id": args.target_id},
        )
        change = {
            "target_type": args.target_type,
            "target_id": args.target_id,
            "expected_revision": args.expected_revision or schema["expected_revision"],
            "mode": args.mode,
            "fields": values,
            "clear_fields": args.clear,
            "override_fields": args.override,
        }
        show({"before": schema["values"], "proposed": change})
        if args.execute:
            show(
                await call(
                    client,
                    "update_metadata",
                    {"changes": [change], "request_id": args.request_id},
                )
            )


if __name__ == "__main__":
    run(main)
