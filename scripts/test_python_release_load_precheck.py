"""Protect load evidence against lost acknowledgements and undercounted resources."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psutil
import pytest
from python_release_load_precheck import (
    FileRecord,
    LoadDriver,
    PhaseState,
    ResourceSampler,
    _freeze_scan_settings,
    _machine_snapshot,
    _request_summaries,
    _seed_rescan_sentinels,
    _supervise_measurement_process,
    _write_failure_evidence,
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


def test_incomplete_evidence_keeps_timeout_and_missing_rescan(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "requests.jsonl").write_text(
        json.dumps(
            {
                "phase": "idle",
                "endpoint": "search",
                "scanActive": False,
                "success": False,
                "errorType": "ReadTimeout",
                "elapsedMs": 10000,
                "startedMonotonic": 10,
                "endedMonotonic": 20,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = _write_failure_evidence(tmp_path, "ReadTimeout")
    assert result["status"] == "failed"
    assert result["rescan"] == {"status": "not_verified"}
    assert result["requestSummaries"][0]["successRate"] == 0
    assert result["requestSummaries"][0]["latencyMs"]["p95"] == 10000
    assert result["requestSummaries"][0]["sampleEvidenceSufficient"] is False
    assert result["phases"] == []
    assert (tmp_path / "failure-summary.json").is_file()


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


class ProgressServer:
    def __init__(self) -> None:
        self.snapshots: dict[str, dict[str, object]] = {}
        self.corrupt_ack = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        resource = request.url.path.split("/")[-2]
        if request.method == "PUT":
            payload = json.loads(request.content)
            snapshot = {**payload, "revision": 1, "receivedAtEpochMillis": 1}
            self.snapshots[resource] = snapshot
            if self.corrupt_ack:
                snapshot["position"]["locator"] = {"wrong": True}
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "acceptedMutationId": payload["mutationId"],
                        "acceptedRevision": 1,
                        "currentSnapshot": snapshot,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "schemaVersion": 5,
                    "progressSnapshot": self.snapshots.get(resource),
                },
            },
        )


def make_driver(tmp_path: Path) -> LoadDriver:
    return LoadDriver(
        base_url="http://test",
        cookies={},
        pool={"bookIds": ["book"], "resourceIds": ["resource"], "formats": ["epub"]},
        phase="test",
        state=PhaseState(),
        output_path=tmp_path / "requests.jsonl",
        abort_event=threading.Event(),
        duration_seconds=1,
        requests_per_second=1,
    )


@pytest.mark.parametrize("damage", ["mutation", "position", "missing", "malformed"])
def test_progress_verification_rejects_lost_acknowledged_write(
    tmp_path: Path, damage: str
) -> None:
    server = ProgressServer()
    driver = make_driver(tmp_path)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        assert driver._request(client, "v5_save", 0)["success"] is True
        assert driver.verify_acknowledged(client)["resourcesVerified"] == 1
        snapshot = server.snapshots["resource"]
        if damage == "mutation":
            snapshot["mutationId"] = str(uuid4())
        elif damage == "position":
            snapshot["position"]["locator"] = {"wrong": True}
        elif damage == "missing":
            del server.snapshots["resource"]
        else:
            del snapshot["revision"]
        with pytest.raises((RuntimeError, ValueError)):
            driver.verify_acknowledged(client)


def test_progress_rejects_200_ok_with_wrong_acknowledged_position(
    tmp_path: Path,
) -> None:
    server = ProgressServer()
    server.corrupt_ack = True
    driver = make_driver(tmp_path)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        result = driver._request(client, "v5_save", 0)
    assert result["success"] is False
    assert driver.acknowledged == {}


def test_sentinels_are_excluded_from_rescan_writes(tmp_path: Path) -> None:
    server = ProgressServer()
    pool = {
        "bookIds": ["b1", "b2", "b3", "b4"],
        "resourceIds": ["r1", "r2", "r3", "r4"],
        "formats": ["epub", "pdf", "cbz", "epub"],
    }
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(server.handle)
    ) as client:
        sentinels, remaining = _seed_rescan_sentinels(
            client, pool, PhaseState(), tmp_path / "sentinels.json", threading.Event()
        )
    assert set(sentinels) == {"r1", "r2", "r3"}
    assert remaining["resourceIds"] == ["r4"]


def test_response_finishing_after_scan_still_counts_as_active(tmp_path: Path) -> None:
    driver = make_driver(tmp_path)
    driver.state.set("scan", scan_active=True)

    def respond(request: httpx.Request) -> httpx.Response:
        driver.state.set("scan", scan_active=False)
        return httpx.Response(200, json={"ok": True, "data": {}})

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        assert driver._request(client, "list", 0)["scanActive"] is True
        assert driver._request(client, "list", 1)["scanActive"] is False


@pytest.mark.parametrize("persisted", [True, False])
def test_freeze_requires_settings_readback(persisted: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert json.loads(request.content) == {
                "watchEnabled": False,
                "intervalMinutes": 1440,
            }
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"watchEnabled": not persisted, "intervalMinutes": 1440},
            },
        )

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        if persisted:
            assert _freeze_scan_settings(client)["watchEnabled"] is False
        else:
            with pytest.raises(RuntimeError, match="not persisted"):
                _freeze_scan_settings(client)


def test_machine_snapshot_decodes_windows_utf8(tmp_path: Path) -> None:
    if os.name != "nt":
        return  # This probe is explicitly a Windows PowerShell boundary.
    snapshot = _machine_snapshot(tmp_path)
    assert "windowsError" not in snapshot
    assert isinstance(snapshot["windows"]["osCaption"], str)


def test_supervisor_bounds_non_daemon_threads_and_descendants(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    code = (
        "import subprocess,sys,threading,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "threading.Thread(target=lambda: time.sleep(60)).start(); "
        f"Path({str(ready)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    process = start_logged_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=os.environ,
        log_path=tmp_path / "supervisor.log",
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        child = psutil.Process(int(ready.read_text()))
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="measurement exceeded"):
            _supervise_measurement_process(process, tmp_path / "state.json", 0.3)
        assert time.monotonic() - started < 20
        assert process.poll() is not None
        assert not child.is_running()
    finally:
        process.stop(timeout=2)
