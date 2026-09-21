"""Preview confirmed system values written to a selected file / 预览系统字段写回指定文件。"""

from common import call, connect, parser, require_execution_key, run, show, submit_plan


async def main() -> None:
    arguments = parser("Write selected metadata fields / 写回选定元数据字段")
    arguments.add_argument("--target-type", choices=["book", "resource", "source_node"])
    arguments.add_argument("--target-id")
    arguments.add_argument("--node-id")
    arguments.add_argument("--mode", choices=["opf", "comicinfo", "embedded"])
    arguments.add_argument("--field", action="append", default=[])
    arguments.add_argument("--clear", action="append", default=[])
    arguments.add_argument(
        "--plan-id", help="Reuse the original plan when retrying / 重试时使用原方案标识"
    )
    args = arguments.parse_args()
    require_execution_key(args)
    if args.plan_id and not args.execute:
        arguments.error("--plan-id requires --execute / 原方案重试需要执行开关")
    if not args.plan_id and not all(
        [args.target_type, args.target_id, args.node_id, args.mode, args.field]
    ):
        arguments.error(
            "Provide all target arguments or --plan-id / 请填写完整目标参数或原方案标识"
        )
    async with connect() as client:
        if args.plan_id:
            await submit_plan(
                client,
                "execute_metadata_writeback",
                {"plan_id": args.plan_id},
                args.request_id,
            )
            return
        schema = await call(
            client,
            "get_metadata_schema",
            {"target_type": args.target_type, "target_id": args.target_id},
        )
        plan = await call(
            client,
            "plan_metadata_writeback",
            {
                "targets": [
                    {
                        "target_type": args.target_type,
                        "target_id": args.target_id,
                        "node_id": args.node_id,
                        "expected_revision": schema["expected_revision"],
                        "mode": args.mode,
                        "fields": args.field,
                        "clear_fields": args.clear,
                    }
                ]
            },
        )
        show(plan)
        if args.execute:
            await submit_plan(
                client, "execute_metadata_writeback", plan, args.request_id
            )


if __name__ == "__main__":
    run(main)
