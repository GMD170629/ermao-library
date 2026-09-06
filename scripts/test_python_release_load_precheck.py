"""Protect load evidence against lost acknowledgements and undercounted resources."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import psutil
import pytest
from python_release_load_precheck import (
    FileRecord,
    LoadDriver,
    PhaseState,
    ResourceSampler,
    _request_summaries,
    stage_dataset,
)
from python_smoke_process import start_logged_process


def test_latency_summary_keeps_failures_and_scan_states(tmp_path: Path) -> None:
    path = tmp_path / "requests.jsonl"
    records = [
        {
            "phase": "rescan",
            "endpoint": "list",
            "scanActive": active,
            "success": success,
            "elapsedMs": duration,
            "errorCode": error,
        }
        for active, success, duration, error in (
            (True, True, 100, None),
            (True, False, 10000, "timeout"),
            (False, True, 20, None),
            (True, False, None, "driver_failure"),
        )
    ]
    path.write_text("\n".join(json.dumps(record) for record in records))
    active, idle = _request_summaries(path)
    assert active["sampleCount"] == 3
    assert active["failureCount"] == 2
    assert active["latencyMs"]["p95"] == 10000
    assert active["errors"] == {"timeout": 1, "driver_failure": 1}
    assert idle["sampleCount"] == 1
    assert idle["latencyMs"]["p95"] == 20


def test_corpus_cannot_write_outside_test_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    sentinel = tmp_path / "private.txt"
    sentinel.write_text("preserve")
    record = FileRecord("../private.txt", "epub", "test", 1, "small", 8, "hash")
    with pytest.raises(ValueError, match="escapes"):
        stage_dataset(
            source,
            target,
            [record],
            start_index=0,
            end_index=1,
            log_path=tmp_path / "stage.log",
        )
    assert sentinel.read_text() == "preserve"
    assert list(target.iterdir()) == []


def test_resource_sampler_counts_real_child_memory(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    child_code = (
        "import time; from pathlib import Path; "
        "memory=bytearray(32*1024*1024); "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
    )
    parent_code = (
        "import subprocess, sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}]); child.wait()"
    )
    process = start_logged_process(
        [sys.executable, "-c", parent_code],
        cwd=tmp_path,
        env=os.environ,
        log_path=tmp_path / "tree.log",
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "child allocation did not become ready"
        root_rss = psutil.Process(process.process.pid).memory_info().rss
        total, pids = ResourceSampler._rss(process.process.pid)
        assert process.process.pid in pids
        assert len(pids) >= 2
        assert total >= root_rss + 32 * 1024 * 1024
    finally:
        process.stop(timeout=2)


def test_progress_verification_rejects_lost_acknowledged_write(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(
                {
                    "ok": True,
                    "data": {"progressSnapshot": {"mutationId": "different-write"}},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return  # Isolated HTTP fixture emits no access log.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    driver = LoadDriver(
        base_url=base_url,
        cookies={},
        pool={},
        phase="test",
        state=PhaseState(),
        output_path=tmp_path / "requests.jsonl",
        abort_event=threading.Event(),
        duration_seconds=1,
        requests_per_second=1,
    )
    driver.acknowledged["test-resource"] = "acknowledged-write"
    try:
        with httpx.Client(base_url=base_url) as client:
            with pytest.raises(RuntimeError, match="acknowledged progress"):
                driver.verify_acknowledged(client)
            driver.acknowledged["test-resource"] = "different-write"
            assert driver.verify_acknowledged(client) == {
                "resourcesVerified": 1,
                "lostAcknowledgedWrites": 0,
            }
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
