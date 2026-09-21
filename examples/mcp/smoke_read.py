"""Read-only SDK smoke check / 只读接入检查。"""

from common import call, connect, run, show


async def main() -> None:
    async with connect() as client:
        show(await call(client, "get_context", {}))
        show(await call(client, "list_libraries", {}))
        show(await call(client, "search_books", {"page": 1, "limit": 5}))


if __name__ == "__main__":
    run(main)
