"""Shared, bounded configuration and real MCP SDK execution for these examples."""

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument(
        "--execute", action="store_true", help="Execute writes / 执行写入"
    )
    result.add_argument(
        "--request-id", help="Stable retry key / 重试时保持相同的请求标识"
    )
    return result


def require_execution_key(args: argparse.Namespace) -> None:
    if args.execute and not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,128}", args.request_id or ""
    ):
        raise ValueError("--execute requires --request-id / 执行需要有效的请求标识")


@asynccontextmanager
async def connect() -> AsyncIterator[Client]:
    url = os.environ.get("ERMAO_MCP_URL", "")
    token = os.environ.get("ERMAO_MCP_TOKEN", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/api/mcp")
        or not token
    ):
        raise ValueError(
            "Configure ERMAO_MCP_URL and ERMAO_MCP_TOKEN / 请配置服务地址和令牌"
        )
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        and os.environ.get("ERMAO_MCP_ALLOW_HTTP") != "1"
    ):
        raise ValueError(
            "Use HTTPS, or explicitly allow trusted LAN HTTP / 请使用 HTTPS 或明确允许可信局域网 HTTP"
        )
    async with (
        httpx2.AsyncClient(
            headers={"Authorization": "Bearer " + token}, timeout=30
        ) as http,
        Client(
            streamable_http_client(url, http_client=http), read_timeout_seconds=30
        ) as client,
    ):
        yield client


async def call(
    client: Client, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    result = await client.call_tool(name, arguments)
    if result.is_error:
        raise RuntimeError(
            f"Tool rejected: {name} / 工具拒绝请求；请在客户端查看授权和方案"
        )
    value = result.structured_content
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError("Invalid structured result / 返回结果格式无效")
    return dict(value)


def show(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


async def wait_operation(client: Client, operation_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 300
    previous = None
    while asyncio.get_running_loop().time() < deadline:
        result = await call(client, "get_operation", {"operation_id": operation_id})
        if result != previous:
            show(result)
            previous = result
        status = result.get("status")
        targets = result.get("targets")
        stages = (
            [item.get("stage") for item in targets if isinstance(item, dict)]
            if isinstance(targets, list)
            else []
        )
        terminal = {"COMPLETED", "CANCELLED", "FAILED", "PARTIAL", "RECOVERY_REQUIRED"}
        if status in terminal or (
            stages and all(stage in terminal for stage in stages)
        ):
            if status in {"FAILED", "PARTIAL", "RECOVERY_REQUIRED"} or any(
                stage in {"FAILED", "RECOVERY_REQUIRED"} for stage in stages
            ):
                raise RuntimeError(
                    "Operation needs attention / 任务存在失败或待恢复项目"
                )
            return
        await asyncio.sleep(2)
    raise TimeoutError(
        "Task still running; keep operation_id and request_id / 任务仍在运行，请保留任务标识与请求标识，不要换键重新提交"
    )


async def submit_plan(
    client: Client, tool: str, plan: dict[str, object], request_id: str
) -> None:
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str):
        raise TypeError("Plan identifier missing / 方案标识缺失")
    result = await call(client, tool, {"plan_id": plan_id, "request_id": request_id})
    show(result)
    operation_id = result.get("operation_id")
    if not isinstance(operation_id, str):
        raise TypeError("Operation identifier missing / 任务标识缺失")
    await wait_operation(client, operation_id)


def run(main: Callable[[], Coroutine[object, object, None]]) -> None:
    try:
        asyncio.run(main())
    except (ValueError, RuntimeError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - CLI boundary redacts SDK URLs and credentials.
        print(
            "Connection or request failed; no automatic resubmission / 连接或请求失败，未自动重新提交",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
