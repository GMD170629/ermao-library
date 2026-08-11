from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings


def test_api_lifespan_does_not_yield_when_data_migration_barrier_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    worker_started = False

    def fail_barrier(*unused: object) -> None:
        del unused
        raise RuntimeError("required startup data migration remains pending")

    def observe_worker_start(*unused: object) -> None:
        nonlocal worker_started
        del unused
        worker_started = True

    monkeypatch.setattr(
        main_module,
        "verify_startup_data_migrations_complete",
        fail_barrier,
    )
    monkeypatch.setattr(
        main_module,
        "start_download_queue_worker",
        observe_worker_start,
    )

    with pytest.raises(RuntimeError, match="remains pending"):
        with TestClient(main_module.create_app(settings)):
            pass

    assert worker_started is False


def test_api_lifespan_verifies_barrier_before_starting_runtime_workers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    calls: list[str] = []

    def verify_barrier(*unused: object) -> None:
        del unused
        calls.append("verify")

    def observe_worker_start(*unused: object) -> None:
        del unused
        calls.append("worker")
        return None

    monkeypatch.setattr(
        main_module,
        "verify_startup_data_migrations_complete",
        verify_barrier,
    )
    monkeypatch.setattr(
        main_module,
        "start_download_queue_worker",
        observe_worker_start,
    )
    monkeypatch.setattr(
        main_module,
        "start_kindle_send_queue_worker",
        lambda *unused: None,
    )
    monkeypatch.setattr(
        main_module,
        "fail_abandoned_health_runs",
        lambda *unused: None,
    )
    monkeypatch.setattr(
        main_module.SystemEventMaintenanceWorker,
        "start",
        lambda unused_self: None,
    )
    monkeypatch.setattr(
        main_module.SystemEventMaintenanceWorker,
        "stop",
        lambda unused_self: None,
    )
    monkeypatch.setattr(
        main_module,
        "start_reader_navigation_maintenance_worker",
        lambda *unused: None,
    )

    with TestClient(main_module.create_app(settings)):
        assert calls[:2] == ["verify", "worker"]

    assert calls.count("verify") == 1
