from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

API_ROOT = Path(__file__).resolve().parents[4]

APP_SOURCE = '''
from app.api.diagnostics_middleware import DiagnosticBoundaryMiddleware
from app.core.logging_config import configure_logging


async def _dispatch(scope, receive, send):
    path = scope["path"]
    if path == "/ok":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
        return
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

SECRETS = (
    "uvicorn-route-secret",
    "uvicorn-stream-secret",
    "uvicorn-query-secret",
    "dXNlcjp1dmljb3JuLXNlY3JldA",
)


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


def _read_stream(port: int) -> bytes:
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
    return b"".join(chunks)


@pytest.mark.parametrize("log_level", ["info", "error"])
def test_real_uvicorn_logs_are_raw_and_access_formatted(
    tmp_path: Path, log_level: str
) -> None:
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
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
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
            log_level,
        ],
        cwd=str(API_ROOT),
        env=env,
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
    )
    try:
        assert _wait_for_port(port), "uvicorn server did not start"

        ok = _get(port, "/ok?token=uvicorn-query-secret")
        assert ok.status_code == 200
        assert ok.text == "ok"

        missing = _get(port, "/missing")
        assert missing.status_code == 404

        route = _get(port, "/route")
        assert route.status_code == 500
        assert "X-Error-Id" not in route.headers
        assert "uvicorn-route-secret" in route.text

        boundary = _get(port, "/boundary")
        assert boundary.status_code == 500

        stream_bytes = _read_stream(port)
    finally:
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()

        stdout_file.close()
        stderr_file.close()

    stdout = stdout_path.read_text(encoding="utf-8")
    stderr = stderr_path.read_text(encoding="utf-8")
    combined = f"{stdout}\n{stderr}"
    assert combined.strip(), "uvicorn produced no output"
    for secret in SECRETS:
        if secret != "uvicorn-query-secret" or log_level == "info":
            assert secret in combined
    assert "Logging error" not in combined
    assert "cannot unpack" not in combined
    assert "TypeError" not in combined

    # Full original errors survive while diagnostic correlation is absent.
    assert "Exception in ASGI application" in stderr
    assert "diagnostic_id=" not in stderr

    if log_level == "info":
        assert '"GET /ok?token=uvicorn-query-secret HTTP/1.1"' in stdout
        assert "200" in stdout
        assert '"GET /missing HTTP/1.1"' in stdout
        assert "404" in stdout
        assert "127.0.0.1" in stdout

    # The streaming failure must not trigger a second response.
    assert b"partial-" in stream_bytes
    assert b"uvicorn-stream-secret" not in stream_bytes
    assert stream_bytes.count(b"HTTP/1.1") == 1
