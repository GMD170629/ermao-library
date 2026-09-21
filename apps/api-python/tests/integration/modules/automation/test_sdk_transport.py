"""Exercise the pinned SDK over a real socket, before business tool wiring."""

import asyncio
import socket
from contextlib import asynccontextmanager

import httpx2
import uvicorn
from fastapi import FastAPI
from mcp import Client
from mcp.server import MCPServer


def test_sdk_fastapi_mount_lifecycle_and_transport_security():
    async def exercise():
        server = MCPServer("ermao-sdk-probe")

        @server.tool()
        def probe(value: str) -> dict[str, str]:
            return {"value": value}

        transport = server.streamable_http_app(
            streamable_http_path="/mcp", json_response=True, stateless_http=True
        )

        @asynccontextmanager
        async def lifespan(_app):
            async with server.session_manager.run():
                yield

        app = FastAPI(lifespan=lifespan)
        app.mount("/api", transport)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        host = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="on", ws="none")
        )
        task = asyncio.create_task(host.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not host.started:
                    if task.done():
                        await task
                        raise AssertionError("HTTP server exited before startup")
                    await asyncio.sleep(0.01)
            url = f"http://127.0.0.1:{port}/api/mcp"
            async with Client(url, read_timeout_seconds=5) as client:
                listed = await client.list_tools()
                assert [tool.name for tool in listed.tools] == ["probe"]
                result = await client.call_tool("probe", {"value": "二毛"})
                assert not result.is_error
                assert result.structured_content == {"value": "二毛"}
            async with httpx2.AsyncClient() as client:
                # No Origin is valid for desktop clients; untrusted browser
                # origins and DNS-rebinding hosts are rejected by the SDK.
                host_response = await client.post(
                    url, headers={"Host": "attacker.invalid"}, json={}
                )
                assert host_response.status_code == 421
                origin_response = await client.post(
                    url, headers={"Origin": "https://attacker.invalid"}, json={}
                )
                assert origin_response.status_code == 403
        finally:
            host.should_exit = True
            try:
                async with asyncio.timeout(10):
                    await task
            finally:
                if not task.done():
                    task.cancel()
                listener.close()

    asyncio.run(exercise())
