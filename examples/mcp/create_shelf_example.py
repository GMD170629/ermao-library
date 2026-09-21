"""Preview a personal shelf; write only with explicit flags / 显式执行才创建书架。"""

from common import call, connect, parser, require_execution_key, run, show


async def main() -> None:
    arguments = parser("Create a personal shelf / 创建个人书架")
    arguments.add_argument("--name", required=True)
    args = arguments.parse_args()
    require_execution_key(args)
    async with connect() as client:
        show(await call(client, "list_shelves", {}))
        proposed = {"name": args.name, "request_id": args.request_id}
        show({"preview": proposed})
        if args.execute:
            show(await call(client, "create_shelf", proposed))


if __name__ == "__main__":
    run(main)
