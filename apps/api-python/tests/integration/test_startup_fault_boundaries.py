from threading import Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import main
from app.services import kindle_queue, log_maintenance


@pytest.mark.parametrize("component", ["download", "kindle", "maintenance"])
def test_optional_start_failure_preserves_api_and_other_consumers(
    monkeypatch, db_session, test_settings, component
):
    workers = {name: Mock() for name in ("download", "kindle", "maintenance")}

    def start(name):
        if component == name:
            raise RuntimeError("startup bug")
        return workers[name]

    monkeypatch.setattr(
        main, "start_download_queue_worker", lambda *a: start("download")
    )
    monkeypatch.setattr(
        main, "start_kindle_send_queue_worker", lambda *a: start("kindle")
    )
    monkeypatch.setattr(
        main, "SystemEventMaintenanceWorker", lambda *a, **kw: start("maintenance")
    )
    app = main.create_app(test_settings, session_factory=lambda: db_session)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/libraries").status_code == 401
    for name, worker in workers.items():
        if name != component:
            worker.request_stop.assert_called_once()
            worker.stop.assert_called_once()


@pytest.mark.parametrize("failed", ["health", "covers"])
def test_startup_maintenance_failures_use_separate_sessions(
    monkeypatch, db_session, test_settings, failed
):
    factory = sessionmaker(bind=db_session.get_bind())
    worker = log_maintenance.SystemEventMaintenanceWorker(
        factory, settings=test_settings
    )
    seen = []

    def operation(name, db):
        seen.append((name, db))
        assert db.scalar(select(1)) == 1
        if name == failed:
            raise RuntimeError("maintenance bug")

    monkeypatch.setattr(
        log_maintenance,
        "fail_abandoned_health_runs",
        lambda db: operation("health", db),
    )
    monkeypatch.setattr(
        log_maintenance,
        "cleanup_default_cover_residue",
        lambda db, settings: operation("covers", db),
    )
    worker._recover_startup_maintenance()
    assert {name for name, _ in seen} == {"health", "covers"}
    assert seen[0][1] is not seen[1][1]
    assert worker._startup_pending == {failed}
    assert all(not db.in_transaction() for _, db in seen)
    worker._recover_startup_maintenance()
    assert len(seen) == 3


def test_kindle_recovery_failure_is_asynchronous_and_gates_claims(
    monkeypatch, db_session, test_settings
):
    attempted = Event()
    heartbeat = Mock()
    process = Mock()
    worker = kindle_queue.KindleSendQueueWorker(
        sessionmaker(bind=db_session.get_bind()), test_settings
    )
    worker._heartbeat = heartbeat

    def fail(db):
        attempted.set()
        raise RuntimeError("recovery bug")

    monkeypatch.setattr(kindle_queue, "recover_interrupted_tasks", fail)
    monkeypatch.setattr(kindle_queue, "process_next_kindle_send_task", process)
    worker.start()
    try:
        assert attempted.wait(2)
    finally:
        worker.stop()
    process.assert_not_called()
    heartbeat.stop.assert_called_once()


def test_api_shutdown_continues_after_one_consumer_fails(
    monkeypatch, db_session, test_settings
):
    download, kindle, maintenance = Mock(), Mock(), Mock()
    download.stop.side_effect = RuntimeError("stop failure")
    download.request_stop.side_effect = RuntimeError("signal failure")
    monkeypatch.setattr(main, "start_download_queue_worker", lambda *a: download)
    monkeypatch.setattr(main, "start_kindle_send_queue_worker", lambda *a: kindle)
    monkeypatch.setattr(
        main, "SystemEventMaintenanceWorker", lambda *a, **kw: maintenance
    )
    with TestClient(main.create_app(test_settings, session_factory=lambda: db_session)):
        pass
    kindle.stop.assert_called_once()
    maintenance.stop.assert_called_once()


def test_core_schema_failure_still_refuses_startup(monkeypatch, test_settings):
    def fail(engine):
        raise RuntimeError("incompatible schema")

    monkeypatch.setattr(main, "verify_current_schema", fail)
    with (
        pytest.raises(RuntimeError, match="incompatible schema"),
        TestClient(main.create_app(test_settings)),
    ):
        pytest.fail("must not be ready")
