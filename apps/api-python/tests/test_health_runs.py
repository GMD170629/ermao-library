import time

from app.services.queue_runtime import queue_runtime_view, record_queue_heartbeat


def _setup_admin(client):
    response = client.post(
        "/api/auth/setup",
        json={"name": "Administrator", "email": "admin@example.com", "password": "starshipnas"},
    )
    assert response.status_code == 201


def test_manual_health_run_exposes_initial_items_and_reaches_terminal_state(client, test_settings):
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

    response = client.post("/api/system/health/runs")
    assert response.status_code == 201
    run = response.json()["data"]["run"]
    assert run["status"] == "running"
    assert run["summary"]["total"] == len(run["items"])
    assert all(item["status"] == "pending" for item in run["items"])

    final = run
    for _ in range(100):
        response = client.get(f"/api/system/health/runs/{run['runId']}")
        assert response.status_code == 200
        final = response.json()["data"]["run"]
        if final["status"] != "running" and final["summary"]["completed"] == final["summary"]["total"]:
            break
        time.sleep(0.02)

    assert final["status"] in {"completed", "warning", "error"}
    assert final["summary"]["completed"] == final["summary"]["total"], final
    assert all(item["status"] in {"ok", "warning", "error", "skipped"} for item in final["items"])

    with client.stream("GET", f"/api/system/health/runs/{run['runId']}/events?after=0") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())
    assert "event: run.completed" in body
    assert f'"runId": "{run["runId"]}"' in body


def test_log_capacity_can_be_updated_from_system_settings(client):
    _setup_admin(client)
    response = client.put("/api/system/log-settings", json={"maxBytes": 2 * 1024 * 1024})
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
