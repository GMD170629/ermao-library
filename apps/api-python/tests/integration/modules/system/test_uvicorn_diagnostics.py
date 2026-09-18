from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

API_ROOT = Path(__file__).resolve().parents[4]

APP_SOURCE = '''
from app.api.diagnostics_middleware import DiagnosticBoundaryMiddleware
from app.core.logging_config import configure_logging


async def _dispatch(scope, receive, send):
    path = scope["path"]
    if path == "/route":
        raise RuntimeError(
            "route failure Cookie: shuku_session=uvicorn-route-secret"
        )
    if path == "/stream":
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"partial-", "more_body": True}
        )
        raise RuntimeError(
            "stream failure Set-Cookie: shuku_session=uvicorn-stream-secret"
        )
    await send({"type": "http.response.start", "status": 404, "headers": []})
    await send({"type": "http.response.body", "body": b"missing"})


_inner = DiagnosticBoundaryMiddleware(
    _dispatch, session_factory=None, respond_with_json=True
)


async def _boundary_layer(scope, receive, send):
    if scope["path"] == "/boundary":
        raise RuntimeError(
            "boundary failure Authorization: "
            "Basic dXNlcjp1dmljb3JuLXNlY3JldA=="
        )
    await _inner(scope, receive, send)


_outer = DiagnosticBoundaryMiddleware(
    _boundary_layer, session_factory=None, respond_with_json=False
)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        configure_logging(force=True)
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    await _outer(scope, receive, send)
'''


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _get(port: int, path: str) -> httpx.Response:
    return httpx.get(
        f"http://127.0.0.1:{port}{path}", timeout=5.0, trust_env=False
    )


def test_real_uvicorn_logs_are_sanitized_across_boundaries(tmp_path: Path) -> None:
    (tmp_path / "diagnostic_uvicorn_app.py").write_text(APP_SOURCE, encoding="utf-8")
    port = _free_port()
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(tmp_path), str(API_ROOT), existing_pythonpath]
        ).rstrip(os.pathsep),
        "PYTHONUNBUFFERED": "1",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "diagnostic_uvicorn_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=str(API_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert _wait_for_port(port), "uvicorn server did not start"

        route = _get(port, "/route")
        assert route.status_code == 500
        assert route.headers["X-Error-Id"].startswith("diag_")
        assert "uvicorn-route-secret" not in route.text

        boundary = _get(port, "/boundary")
        assert boundary.status_code == 500

        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
            sock.sendall(
                b"GET /stream HTTP/1.1\r\nHost: localhost\r\n"
                b"Connection: close\r\n\r\n"
            )
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        stream_bytes = b"".join(chunks)
    finally:
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate()

    assert stderr, "uvicorn produced no server output"
    for secret in (
        "uvicorn-route-secret",
        "uvicorn-stream-secret",
        "dXNlcjp1dmljb3JuLXNlY3JldA",
    ):
        assert secret not in stderr, f"server log leaked {secret}"
    assert "Exception in ASGI application" in stderr
    assert "diagnostic_id=diag_" in stderr

    # The streaming failure must not trigger a second response.
    assert b"partial-" in stream_bytes
    assert b"uvicorn-stream-secret" not in stream_bytes
    assert stream_bytes.count(b"HTTP/1.1") == 1
