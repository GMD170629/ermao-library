import time
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models as _models  # noqa: F401
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.import_pipeline import ImportTask
from app.services.queue_runtime import queue_runtime_view, record_queue_heartbeat


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
    test_settings.resolved_monitor_root.mkdir(parents=True)
    for path in (
        test_settings.resolved_storage_root,
        test_settings.database_path.parent,
        test_settings.resolved_storage_root / "library",
        test_settings.resolved_storage_root / "covers",
        test_settings.resolved_storage_root / "indexes",
        test_settings.resolved_storage_root / "backups",
        test_settings.conversion_root,
        test_settings.conversion_temp_root,
        test_settings.resolved_storage_root / "logs",
        test_settings.resolved_storage_root / "secrets",
    ):
        path.mkdir(parents=True, exist_ok=True)
    _setup_admin(client)
    pending_created_at = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)
    db_session.add(
        ImportTask(
            id="health-pending-import",
            origin="manual",
            status="PENDING",
            source_path="/library/pending.epub",
            created_at=pending_created_at,
            updated_at=pending_created_at,
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
    assert isinstance(import_queue["details"]["runtime"]["heartbeatAt"], int)

    with client.stream(
        "GET", f"/api/system/health/runs/{run['runId']}/events?after=0"
    ) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())
    assert "event: run.completed" in body
    assert f'"runId": "{run["runId"]}"' in body


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


def test_import_queue_clear_operation_is_idempotent_and_conflicts_with_restart(
    client,
    db_session,
):
    _setup_admin(client)
    record_queue_heartbeat(db_session, "import", "test-worker", 2)

    first = client.post("/api/import-tasks/clear")
    assert first.status_code == 202
    first_data = first.json()["data"]
    assert first_data["created"] is True
    assert first_data["operation"]["action"] == "clear"
    assert first_data["operation"]["status"] == "requested"

    repeated = client.post("/api/import-tasks/clear")
    assert repeated.status_code == 202
    repeated_data = repeated.json()["data"]
    assert repeated_data["created"] is False
    assert repeated_data["operation"]["id"] == first_data["operation"]["id"]

    restart = client.post("/api/system/queues/import/restart")
    assert restart.status_code == 409
    assert restart.json()["error"]["code"] == "QUEUE_OPERATION_CONFLICT"

    operation = client.get(
        f"/api/system/queue-operations/{first_data['operation']['id']}"
    )
    assert operation.status_code == 200
    assert operation.json()["data"]["operation"]["action"] == "clear"


def test_import_queue_clear_rejects_an_unavailable_worker(client):
    _setup_admin(client)

    response = client.post("/api/import-tasks/clear")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_QUEUE_OFFLINE"
