import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.bootstrap.system import record_queue_heartbeat
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import Library, LibraryImportTask
from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.infrastructure import health_runs
from app.modules.system.infrastructure.queue_runtime import queue_runtime_view


def _setup_admin(client):
    response = client.post(
        "/api/auth/setup",
        json={
            "name": "Administrator",
            "email": "admin@example.com",
            "password": "starshipnas",
        },
    )
    assert response.status_code == 201


@pytest.fixture()
def persistent_health_client(
    test_settings: Settings,
) -> Generator[tuple[TestClient, Session], None, None]:
    """Use independent sessions against a real file for background health work."""

    test_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{test_settings.database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    database_session = session_factory()
    app = create_app(test_settings, session_factory=lambda: database_session)

    def override_settings() -> Settings:
        return test_settings

    def override_db() -> Generator[Session, None, None]:
        yield database_session

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client, database_session
    database_session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_manual_health_run_exposes_initial_items_and_reaches_terminal_state(
    persistent_health_client,
    test_settings,
):
    client, db_session = persistent_health_client
    test_settings.resolved_library_root.mkdir(parents=True)
    for path in (
        test_settings.resolved_storage_root,
        test_settings.database_path.parent,
        test_settings.resolved_storage_root / "library",
        test_settings.resolved_storage_root / "covers",
        test_settings.resolved_storage_root / "indexes",
        test_settings.resolved_storage_root / "backups",
        test_settings.resolved_storage_root / "logs",
        test_settings.resolved_storage_root / "secrets",
    ):
        path.mkdir(parents=True, exist_ok=True)
    _setup_admin(client)
    pending_created_at = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)
    health_library = Library(
        id="health-library",
        name="Health library",
        root_path=str(test_settings.resolved_library_root),
        organization_mode="FLAT",
    )
    db_session.add(health_library)
    db_session.flush()
    db_session.add(
        LibraryImportTask(
            id="health-pending-import",
            kind="SCAN_LIBRARY",
            library_id=health_library.id,
            state="QUEUED",
            created_at=pending_created_at,
        )
    )
    db_session.flush()
    record_queue_heartbeat(db_session, "import", "health-test-worker", 2)

    response = client.post("/api/system/health/runs")
    assert response.status_code == 201
    run = response.json()["data"]["run"]
    assert run["status"] == "running"
    assert run["summary"]["total"] == len(run["items"])
    assert all(item["status"] == "pending" for item in run["items"])

    final = run
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/system/health/runs/{run['runId']}")
        assert response.status_code == 200
        final = response.json()["data"]["run"]
        if (
            final["status"] != "running"
            and final["summary"]["completed"] == final["summary"]["total"]
        ):
            break
        time.sleep(0.05)

    assert final["status"] in {"completed", "warning", "error"}
    assert final["summary"]["completed"] == final["summary"]["total"], final
    assert all(
        item["status"] in {"ok", "warning", "error", "skipped"}
        for item in final["items"]
    )
    import_queue = next(item for item in final["items"] if item["id"] == "queue:import")
    assert import_queue["status"] == "ok"
    assert import_queue["messageCode"] == "health.queue.ok"
    assert import_queue["details"]["oldestPendingAt"] == "2026-07-31T08:30:00Z"
    assert import_queue["details"]["pending"] == 1
    assert "runtime" not in import_queue["details"]

    with client.stream(
        "GET", f"/api/system/health/runs/{run['runId']}/events?after=0"
    ) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())
    assert "event: run.completed" in body
    assert f'"runId": "{run["runId"]}"' in body


def test_health_external_checks_run_without_a_checked_out_read_session(
    tmp_path: Path,
    test_settings: Settings,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'health-isolation.sqlite'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    with factory() as db:
        prepared = health_runs.prepare_health_run_creation(
            db,
            test_settings,
            "health-session-actor",
        )
        with SystemWriteTransaction(db):
            health_runs.write_prepared_health_run_creation(db, prepared)

    checked_out_counts: list[int] = []

    def isolated_check(*_args, **_kwargs):
        checked_out_counts.append(engine.pool.checkedout())
        return "ok", "health.test.ok", {}

    monkeypatch.setattr(health_runs, "_execute_item", isolated_check)
    health_runs.run_health_checks(
        factory,
        True,
        test_settings,
        str(prepared.snapshot["runId"]),
    )

    assert checked_out_counts
    assert set(checked_out_counts) == {0}
    engine.dispose()


def test_log_capacity_can_be_updated_from_system_settings(client):
    _setup_admin(client)
    response = client.put(
        "/api/system/log-settings", json={"maxBytes": 2 * 1024 * 1024}
    )
    assert response.status_code == 200
    assert response.json()["data"]["storage"]["maxBytes"] == 2 * 1024 * 1024

    invalid = client.put("/api/system/log-settings", json={"maxBytes": 100})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_LOG_MAX_BYTES"


def test_queue_heartbeat_reports_staleness(db_session):
    record_queue_heartbeat(db_session, "import", "test-worker", 2)
    runtime = queue_runtime_view(db_session, "import")
    assert runtime is not None
    assert runtime["status"] == "running"
    assert runtime["stale"] is False
    assert runtime["staleAfterMs"] == 30_000


def test_retired_import_queue_clear_route_is_not_available(client):
    _setup_admin(client)
    response = client.post("/api/import-tasks/clear")
    assert response.status_code == 404
