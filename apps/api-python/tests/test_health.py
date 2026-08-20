import json
from datetime import UTC, datetime
from pathlib import Path

from app.models.auth import User
from app.models.library import Library
from app.models.settings import SystemHealthRun


def _setup_admin(client) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "name": "Administrator",
            "email": "admin@example.com",
            "password": "starshipnas",
        },
    )
    assert response.status_code == 201


def _disable_fixture_library(db_session) -> None:
    for library in db_session.query(Library).all():
        library.enabled = False
    db_session.commit()


def test_health_response_shape(client, db_session, test_settings):
    _disable_fixture_library(db_session)
    monitor = test_settings.resolved_monitor_root
    assert monitor is not None
    monitor.mkdir(parents=True)
    _setup_admin(client)

    response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"
    assert isinstance(payload["data"]["checks"], list)
    monitor_check = next(
        check
        for check in payload["data"]["checks"]
        if check["name"] == "monitorRootReadable"
    )
    assert monitor_check["status"] == "unknown"
    assert all(
        check["name"] != "ebookConversion" for check in payload["data"]["checks"]
    )


def test_health_aggregates_enabled_library_readability(client, db_session, tmp_path):
    _disable_fixture_library(db_session)
    _setup_admin(client)
    first = tmp_path / "first-library"
    second = tmp_path / "second-library"
    first.mkdir()
    second.mkdir()
    db_session.add_all(
        [
            Library(
                organization_mode="FLAT",
                name="First",
                root_path=str(first),
                enabled=True,
            ),
            Library(
                organization_mode="FLAT",
                name="Second",
                root_path=str(second),
                enabled=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/system/health")

    monitor_check = next(
        check
        for check in response.json()["data"]["checks"]
        if check["name"] == "monitorRootReadable"
    )
    assert monitor_check["status"] == "ok"
    assert monitor_check["message"] == "2 个书库可读"


def test_missing_enabled_library_does_not_block_service_readiness(
    client, db_session, tmp_path
):
    _disable_fixture_library(db_session)
    _setup_admin(client)
    missing = tmp_path / "detached-library"
    db_session.add(
        Library(
            organization_mode="FLAT",
            name="Detached",
            root_path=str(missing),
            enabled=True,
        )
    )
    db_session.commit()

    readiness_response = client.get("/api/health")
    diagnostics_response = client.get("/api/system/health")

    assert readiness_response.status_code == 200
    assert readiness_response.json()["data"]["status"] == "ok"
    assert diagnostics_response.status_code == 200, diagnostics_response.text
    assert diagnostics_response.json()["data"]["status"] == "ok"
    monitor_check = next(
        check
        for check in diagnostics_response.json()["data"]["checks"]
        if check["name"] == "monitorRootReadable"
    )
    assert monitor_check["status"] == "warning"
    assert str(missing) in monitor_check["message"]


def test_health_reports_an_unreadable_enabled_library(
    client, db_session, tmp_path, monkeypatch
):
    _disable_fixture_library(db_session)
    _setup_admin(client)
    blocked = tmp_path / "blocked-library"
    blocked.mkdir()
    db_session.add(
        Library(
            organization_mode="FLAT",
            name="Blocked",
            root_path=str(blocked),
            enabled=True,
        )
    )
    db_session.commit()
    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):
        if path == blocked:
            raise PermissionError("permission denied")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)

    response = client.get("/api/system/health")

    monitor_check = next(
        check
        for check in response.json()["data"]["checks"]
        if check["name"] == "monitorRootReadable"
    )
    assert monitor_check["status"] == "warning"
    assert "书库不可读" in monitor_check["message"]


def test_health_allows_no_configured_libraries(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["service"] == "ermao-books"
    assert payload["data"]["status"] == "ok"


def test_db_ping_succeeds(client):
    response = client.get("/api/__db-ping")
    assert response.status_code == 200
    assert response.json()["data"]["database"] == "ok"


def test_health_run_http_and_sse_timestamps_are_epoch_milliseconds(client, db_session):
    _setup_admin(client)
    actor = db_session.query(User).filter(User.email == "admin@example.com").one()
    started_at = 1_785_132_000_000
    finished_at = 1_785_132_000_250
    snapshot = {
        "runId": "health-contract",
        "status": "completed",
        "version": 2,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "groups": [{"id": "storage", "labelCode": "health.group.storage"}],
        "items": [
            {
                "id": "database",
                "group": "storage",
                "labelCode": "health.item.database",
                "kind": "database",
                "options": {},
                "status": "ok",
                "messageCode": "health.database.ok",
                "messageParams": {},
                "details": {},
                "startedAt": started_at,
                "finishedAt": finished_at,
                "durationMs": 250,
            }
        ],
        "summary": {
            "total": 1,
            "completed": 1,
            "ok": 1,
            "warning": 0,
            "error": 0,
            "skipped": 0,
        },
    }
    db_session.add(
        SystemHealthRun(
            id="health-contract",
            actor_user_id=actor.id,
            status="completed",
            version=2,
            snapshot=json.dumps(snapshot),
            started_at=datetime.fromtimestamp(started_at / 1000, UTC),
            finished_at=datetime.fromtimestamp(finished_at / 1000, UTC),
            created_at=datetime.fromtimestamp(started_at / 1000, UTC),
            updated_at=datetime.fromtimestamp(finished_at / 1000, UTC),
        )
    )
    db_session.commit()

    response = client.get("/api/system/health/runs/health-contract")
    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["startedAt"] == started_at
    assert run["finishedAt"] == finished_at
    assert run["items"][0]["startedAt"] == started_at
    assert run["items"][0]["finishedAt"] == finished_at

    with client.stream(
        "GET", "/api/system/health/runs/health-contract/events"
    ) as stream:
        event_text = stream.read().decode()
    data_line = next(
        line for line in event_text.splitlines() if line.startswith("data: ")
    )
    event_run = json.loads(data_line.removeprefix("data: "))["run"]
    assert event_run["startedAt"] == started_at
    assert event_run["finishedAt"] == finished_at
    assert event_run["items"][0]["finishedAt"] == finished_at
