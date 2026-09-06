"""Focused tests for the release-only Python smoke entry points."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import httpx
import pytest

SCRIPTS_ROOT = Path(__file__).resolve().parent
# The test imports the two standalone smoke modules after their own path
# bootstrap; E402 is not selected by the current scripts lint configuration.
sys.path.insert(0, str(SCRIPTS_ROOT))

from python_backend_sample_smoke import (
    assert_exact_asset_range,
    read_complete_original,
)
from python_smoke_process import LoggedProcess, start_logged_process


def _wait_for_log_marker(
    log_path: Path,
    marker: str,
    managed: LoggedProcess,
    *,
    timeout: float = 3,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_path.is_file() and marker in log_path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return
        if managed.poll() is not None:
            pytest.fail(f"child exited before writing {marker!r}: {managed.returncode}")
        time.sleep(0.05)
    pytest.fail(f"child did not write {marker!r} within {timeout}s")


def test_logged_process_reads_utf8_from_an_early_exit_and_can_stop_twice(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "early-exit.log"
    managed = start_logged_process(
        [
            sys.executable,
            "-c",
            "print('早退 smoke', flush=True)",
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        log_path=log_path,
    )

    assert managed.wait(timeout=5) == 0
    first = managed.stop(timeout=0.25)
    second = managed.stop(timeout=0.25)

    assert first == second
    assert "早退 smoke" in first


def test_logged_process_redirects_large_output_and_stops_with_a_bound(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "child.log"
    managed: LoggedProcess | None = None
    try:
        managed = start_logged_process(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.write('x' * 200000); sys.stdout.flush(); time.sleep(60)",
            ],
            cwd=tmp_path,
            env=dict(os.environ),
            log_path=log_path,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if log_path.is_file() and log_path.stat().st_size >= 200000:
                break
            if managed.poll() is not None:
                pytest.fail(f"child exited before writing output: {managed.returncode}")
            time.sleep(0.05)
        assert log_path.stat().st_size >= 200000

        started = time.monotonic()
        output = managed.stop(timeout=0.25)
        elapsed = time.monotonic() - started
        assert elapsed < 10
        assert len(output) == 200000
        assert managed.poll() is not None
        assert managed.process.stdout is None
    finally:
        if managed is not None and managed.poll() is None:
            managed.stop(timeout=0.25)


def test_logged_process_force_kills_a_child_ignoring_platform_signal(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "force-kill.log"
    graceful_signal = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
    ignored_signal_expression = (
        "signal.SIGBREAK" if os.name == "nt" else "signal.SIGTERM"
    )
    managed = start_logged_process(
        [
            sys.executable,
            "-c",
            (
                "import signal,time;"
                f"signal.signal({ignored_signal_expression}, signal.SIG_IGN);"
                "print('force-kill smoke', flush=True);"
                "time.sleep(60)"
            ),
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        log_path=log_path,
    )
    try:
        _wait_for_log_marker(log_path, "force-kill smoke", managed)
        managed.process.send_signal(graceful_signal)
        time.sleep(0.2)
        assert managed.poll() is None

        started = time.monotonic()
        output = managed.stop(timeout=0.1)
        elapsed = time.monotonic() - started

        assert elapsed < 10
        assert "force-kill smoke" in output
        assert managed.poll() is not None
        if os.name == "nt":
            assert managed.returncode != 0
        else:
            force_signal_number = int(getattr(signal, "SIGKILL", signal.SIGTERM))
            assert managed.returncode == -force_signal_number
    finally:
        if managed.poll() is None:
            managed.stop(timeout=0.25)


def test_asset_http_checks_accept_good_bytes_and_reject_bad_range_or_hash(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "sample.epub"
    source_bytes = b"reader fixture"
    source_path.write_bytes(source_bytes)
    size = len(source_bytes)

    def good_handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("range") == "bytes=0-4":
            return httpx.Response(
                206,
                headers={
                    "content-range": f"bytes 0-4/{size}",
                    "content-length": "5",
                },
                content=source_bytes[:5],
            )
        return httpx.Response(
            200,
            headers={"content-length": str(size)},
            content=source_bytes,
        )

    with httpx.Client(
        transport=httpx.MockTransport(good_handler),
        base_url="http://smoke.test",
    ) as client:
        assert_exact_asset_range(client, "/asset", source_path)
        assert read_complete_original(client, "/original", source_path) == source_bytes

    def bad_range_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206,
            headers={
                "content-range": f"bytes 0-3/{size}",
                "content-length": "5",
            },
            content=source_bytes[:5],
        )

    with (
        httpx.Client(
            transport=httpx.MockTransport(bad_range_handler),
            base_url="http://smoke.test",
        ) as client,
        pytest.raises(AssertionError),
    ):
        assert_exact_asset_range(client, "/asset", source_path)

    def bad_hash_handler(_request: httpx.Request) -> httpx.Response:
        bad_bytes = b"wrong fixture!"
        return httpx.Response(
            200,
            headers={"content-length": str(len(bad_bytes))},
            content=bad_bytes,
        )

    with (
        httpx.Client(
            transport=httpx.MockTransport(bad_hash_handler),
            base_url="http://smoke.test",
        ) as client,
        pytest.raises(AssertionError),
    ):
        read_complete_original(client, "/original", source_path)
