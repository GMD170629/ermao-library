from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from appv2.composition.api import create_app
from appv2.composition.container import build_container
from appv2.platform.config import Settings, get_settings


@pytest.mark.postgres
def test_setup_login_catalog_and_health_on_postgresql_18(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = os.getenv("APPV2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("APPV2_TEST_DATABASE_URL is not configured")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        major = int(str(connection.execute(text("SHOW server_version")).scalar_one()).split(".")[0])
    assert major == 18

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("SESSION_SECRET", "integration-test-session-secret")
    get_settings.cache_clear()
    backend_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(backend_root / "alembic-v2.ini"), "head")

    settings = Settings(
        database_url=SecretStr(database_url),
        session_secret=SecretStr("integration-test-session-secret"),
        storage_root=tmp_path,
        monitor_root=tmp_path / "monitor",
    )
    email = f"integration-{uuid.uuid4().hex}@example.com"
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v2/auth/setup",
            json={
                "email": email,
                "displayName": "Integration Admin",
                "password": "correct horse battery staple",
                "locale": "en-US",
            },
        )
        if setup.status_code == 409:
            pytest.skip("the configured PostgreSQL database is not an isolated test database")
        assert setup.status_code == 201, setup.text
        created = client.post(
            "/api/v2/catalog/works",
            json={
                "title": "Architecture Test Book",
                "author": "Codex",
                "mediaType": "book",
                "metadata": {"source": "integration"},
            },
        )
        assert created.status_code == 201, created.text
        works = client.get("/api/v2/catalog/works?pageSize=24")
        assert works.status_code == 200
        assert works.json()["total"] >= 1
        health = client.get("/api/v2/operations/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        account = client.get("/api/v2/account")
        assert account.status_code == 200
        account_id = account.json()["id"]
        preferences = client.patch(
            "/api/v2/account/preferences",
            json={"values": {"libraryView": "grid", "pageSize": 24}},
        )
        assert preferences.status_code == 200
        assert preferences.json()["values"]["libraryView"] == "grid"

        member = client.post(
            "/api/v2/admin/users",
            json={
                "email": f"member-{uuid.uuid4().hex}@example.com",
                "displayName": "Integration Member",
                "password": "another correct horse battery staple",
                "locale": "zh-CN",
                "role": "member",
            },
        )
        assert member.status_code == 201, member.text
        users = client.get("/api/v2/admin/users?pageSize=10")
        assert users.status_code == 200
        assert users.json()["total"] == 2

        shelf = client.post(
            "/api/v2/catalog/shelves",
            json={
                "name": "Integration Shelf",
                "description": "Cross-module journey",
                "kind": "manual",
                "bookIds": [created.json()["id"]],
            },
        )
        assert shelf.status_code == 201, shelf.text
        shelf_detail = client.get(f"/api/v2/catalog/shelves/{shelf.json()['id']}")
        assert shelf_detail.status_code == 200
        assert shelf_detail.json()["bookIds"] == [created.json()["id"]]
        categories = client.get("/api/v2/catalog/categories?kind=TAG&pageSize=10")
        assert categories.status_code == 200

        monitor = tmp_path / "monitor"
        monitored = monitor / "library"
        monitored.mkdir(parents=True)
        (monitored / "Monitored Book.txt").write_text("monitored content", encoding="utf-8")
        folder = client.post(
            "/api/v2/ingestion/folders",
            json={
                "path": str(monitored),
                "recursive": True,
                "moveSource": False,
                "options": {"ignoreHidden": True},
            },
        )
        assert folder.status_code == 201, folder.text
        tree = client.get("/api/v2/ingestion/folders/tree")
        assert tree.status_code == 200
        assert tree.json()["monitorRoot"] == str(monitor)
        scan = client.post(
            "/api/v2/ingestion/imports/scan-directory",
            json={"path": str(monitored)},
        )
        assert scan.status_code == 202, scan.text
        upload = client.post(
            "/api/v2/ingestion/imports/upload",
            files={"file": ("Uploaded Book.txt", b"uploaded content", "text/plain")},
        )
        assert upload.status_code == 202, upload.text

        worker_container = build_container(settings)
        try:
            assert worker_container.ingestion_worker.run_once("integration-worker")
            assert worker_container.ingestion_worker.run_once("integration-worker")
        finally:
            worker_container.close()
        import_jobs = client.get("/api/v2/ingestion/imports?pageSize=10")
        assert import_jobs.status_code == 200
        completed_jobs = [
            job for job in import_jobs.json()["items"] if job["status"] == "completed"
        ]
        assert len(completed_jobs) == 2
        edition_id = completed_jobs[0]["resultId"]

        bootstrap = client.get(f"/api/v2/reading/editions/{edition_id}/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        assert bootstrap.json()["accountId"] == account_id
        progress = client.put(
            f"/api/v2/reading/editions/{edition_id}/progress",
            json={
                "deviceId": "integration-browser",
                "position": {"location": {"type": "epub", "progression": 0.5}},
                "percentage": 0.5,
            },
        )
        assert progress.status_code == 200, progress.text
        bookmark = client.put(
            f"/api/v2/reading/editions/{edition_id}/bookmarks",
            json={
                "clientId": "integration-bookmark",
                "label": "Middle",
                "position": {"location": {"type": "epub", "progression": 0.5}},
            },
        )
        assert bookmark.status_code == 201, bookmark.text
        assert client.get(f"/api/v2/reading/editions/{edition_id}/bookmarks").json()["total"] == 1
        reading_preference = client.put(
            "/api/v2/reading/preferences",
            json={
                "scope": "edition",
                "targetId": edition_id,
                "values": {"theme": "night"},
            },
        )
        assert reading_preference.status_code == 200

        provider = client.post(
            "/api/v2/metadata/providers",
            json={
                "slug": f"integration-{uuid.uuid4().hex}",
                "name": "Integration Provider",
                "enabled": False,
                "priority": 100,
                "config": {},
            },
        )
        assert provider.status_code == 201, provider.text
        metadata_job = client.post(
            "/api/v2/metadata/jobs",
            json={"workId": created.json()["id"], "query": "Architecture Test Book"},
        )
        assert metadata_job.status_code == 202, metadata_job.text

        source = client.post(
            "/api/v2/discovery/sources",
            json={
                "name": "Integration Source",
                "kind": "json-http",
                "baseUrl": "https://example.com/books",
                "enabled": False,
                "config": {},
            },
        )
        assert source.status_code == 201, source.text
        assert client.get("/api/v2/discovery/sources").json()["total"] == 1

        kindle_settings = client.put(
            "/api/v2/delivery/kindle/settings",
            json={
                "kindleEmail": "reader@kindle.com",
                "convertBeforeSend": False,
                "options": {},
            },
        )
        assert kindle_settings.status_code == 200, kindle_settings.text
        email_settings = client.put(
            "/api/v2/delivery/email/settings",
            json={
                "host": "smtp.example.com",
                "port": 587,
                "username": "mailer",
                "password": "secret",
                "sender": "sender@example.com",
                "useTls": True,
            },
        )
        assert email_settings.status_code == 200, email_settings.text

        settings_response = client.put(
            "/api/v2/operations/settings",
            json={"values": {"metadata.external.enabled": {"value": "true"}}},
        )
        assert settings_response.status_code == 200
        assert client.get("/api/v2/operations/events").json()["total"] >= 1
        backup = client.post("/api/v2/operations/backups")
        assert backup.status_code == 202, backup.text
        assert backup.json()["appVersion"] == "0.4.0"
        assert client.get("/api/v2/reporting/dashboard").status_code == 200
        assert client.get("/api/v2/reporting/management").status_code == 200
