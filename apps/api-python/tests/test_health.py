import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.auth import User
from app.models.settings import MonitorFolder, SystemHealthRun


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


def test_health_response_shape(client, test_settings):
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
    conversion = next(check for check in payload["data"]["checks"] if check["name"] == "ebookConversion")
    assert conversion["details"]["converter"] == "libmobi+shuku-internal"
    assert {engine["converter"] for engine in conversion["details"]["engines"]} == {"libmobi", "shuku-internal"}


def test_health_aggregates_enabled_monitor_folder_readability(
    client, db_session, tmp_path
):
    _setup_admin(client)
    first = tmp_path / "first-library"
    second = tmp_path / "second-library"
    first.mkdir()
    second.mkdir()
    db_session.add_all(
        [
            MonitorFolder(name="First", root_path=str(first), enabled=True),
            MonitorFolder(name="Second", root_path=str(second), enabled=True),
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
    assert monitor_check["message"] == "2 个监控文件夹可读"


def test_health_reports_an_unreadable_enabled_monitor_folder(
    client, db_session, tmp_path, monkeypatch
):
    _setup_admin(client)
    blocked = tmp_path / "blocked-library"
    blocked.mkdir()
    db_session.add(MonitorFolder(name="Blocked", root_path=str(blocked), enabled=True))
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
    assert monitor_check["status"] == "error"
    assert "监控文件夹不可读" in monitor_check["message"]


def test_health_allows_no_configured_monitor_folders(client):
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
            started_at=datetime.fromtimestamp(started_at / 1000, timezone.utc),
            finished_at=datetime.fromtimestamp(finished_at / 1000, timezone.utc),
            created_at=datetime.fromtimestamp(started_at / 1000, timezone.utc),
            updated_at=datetime.fromtimestamp(finished_at / 1000, timezone.utc),
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

    with client.stream("GET", "/api/system/health/runs/health-contract/events") as stream:
        event_text = stream.read().decode()
    data_line = next(line for line in event_text.splitlines() if line.startswith("data: "))
    event_run = json.loads(data_line.removeprefix("data: "))["run"]
    assert event_run["startedAt"] == started_at
    assert event_run["finishedAt"] == finished_at
    assert event_run["items"][0]["finishedAt"] == finished_at
