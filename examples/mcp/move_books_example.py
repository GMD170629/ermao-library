"""Preview one explicit move before submission / 先预览一项明确移动。"""

from common import call, connect, parser, require_execution_key, run, show, submit_plan


async def main() -> None:
    arguments = parser("Move one selected source node / 移动指定源节点")
    arguments.add_argument("--node-id")
    arguments.add_argument("--destination-library-id")
    arguments.add_argument("--destination-path")
    arguments.add_argument(
        "--plan-id", help="Reuse the original plan when retrying / 重试时使用原方案标识"
    )
    args = arguments.parse_args()
    require_execution_key(args)
    if args.plan_id and not args.execute:
        arguments.error("--plan-id requires --execute / 原方案重试需要执行开关")
    if not args.plan_id and not all(
        [args.node_id, args.destination_library_id, args.destination_path]
    ):
        arguments.error(
            "Provide all target arguments or --plan-id / 请填写完整目标参数或原方案标识"
        )
    async with connect() as client:
        if args.plan_id:
            await submit_plan(
                client,
                "execute_file_operations",
                {"plan_id": args.plan_id},
                args.request_id,
            )
            return
        plan = await call(
            client,
            "plan_file_operations",
            {
                "moves": [
                    {
                        "source_node_id": args.node_id,
                        "destination_library_id": args.destination_library_id,
                        "destination_relative_path": args.destination_path,
                    }
                ]
            },
        )
        show(plan)
        if args.execute:
            await submit_plan(client, "execute_file_operations", plan, args.request_id)


if __name__ == "__main__":
    run(main)
