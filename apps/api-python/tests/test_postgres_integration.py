# ruff: noqa: S105

from __future__ import annotations

import os
import re
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
        assert client.get("/api/v2/auth/setup/status").json() == {"required": False}
        assert (
            client.post(
                "/api/v2/auth/setup",
                json={
                    "email": f"second-{email}",
                    "displayName": "Second Administrator",
                    "password": "correct horse battery staple",
                    "locale": "en-US",
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v2/auth/login",
                json={"email": email, "password": "definitely incorrect"},
            ).status_code
            == 401
        )
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
        account_update = client.patch(
            "/api/v2/account",
            json={"displayName": "Updated Integration Admin", "locale": "zh-CN"},
        )
        assert account_update.status_code == 200, account_update.text
        assert account_update.json()["displayName"] == "Updated Integration Admin"
        assert (
            client.patch(
                "/api/v2/account",
                json={
                    "password": "replacement administrator password",
                    "currentPassword": "incorrect current password",
                },
            ).status_code
            == 403
        )
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
        assert (
            client.post(
                "/api/v2/admin/users",
                json={
                    "email": member.json()["email"],
                    "displayName": "Duplicate Integration Member",
                    "password": "another correct horse battery staple",
                    "locale": "zh-CN",
                    "role": "member",
                },
            ).status_code
            == 409
        )
        assert (
            client.patch(
                "/api/v2/account",
                json={"email": member.json()["email"]},
            ).status_code
            == 409
        )
        users = client.get("/api/v2/admin/users?pageSize=10")
        assert users.status_code == 200
        assert users.json()["total"] == 2
        member_id = member.json()["id"]
        disabled_member = client.patch(
            f"/api/v2/admin/users/{member_id}",
            json={"disabled": True},
        )
        assert disabled_member.status_code == 200, disabled_member.text
        assert disabled_member.json()["disabled"] is True
        enabled_member = client.patch(
            f"/api/v2/admin/users/{member_id}",
            json={
                "displayName": "Managed Integration Member",
                "disabled": False,
                "scopes": ["catalog:read", "reading:write"],
                "monitorFolderIds": [],
            },
        )
        assert enabled_member.status_code == 200, enabled_member.text
        assert enabled_member.json()["displayName"] == "Managed Integration Member"
        missing_account_id = uuid.uuid4()
        assert (
            client.patch(
                f"/api/v2/admin/users/{account_id}",
                json={"disabled": True},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/v2/admin/users/{missing_account_id}",
                json={"displayName": "Missing Account"},
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"/api/v2/admin/users/{missing_account_id}/password",
                json={"password": "missing account password"},
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v2/admin/users/{account_id}").status_code == 409
        assert client.delete(f"/api/v2/admin/users/{missing_account_id}").status_code == 404
        managed_password = "managed member password value"
        assert (
            client.put(
                f"/api/v2/admin/users/{member_id}/password",
                json={"password": managed_password},
            ).status_code
            == 204
        )
        with TestClient(create_app(settings)) as member_client:
            member_login = member_client.post(
                "/api/v2/auth/login",
                json={
                    "email": member.json()["email"],
                    "password": managed_password,
                },
            )
            assert member_login.status_code == 200, member_login.text
            assert member_client.get("/api/v2/catalog/works").status_code == 200
            assert member_client.get("/api/v2/operations/settings").status_code == 403
            assert (
                member_client.post(
                    "/api/v2/catalog/works",
                    json={
                        "title": "Forbidden member write",
                        "mediaType": "book",
                    },
                ).status_code
                == 403
            )
            assert member_client.get("/api/v2/delivery/email/status").status_code == 403
            assert member_client.post("/api/v2/auth/logout").status_code == 204
            assert member_client.get("/api/v2/account").status_code == 401

        reset_request = client.post(
            "/api/v2/auth/password-reset/request",
            headers={"Accept-Language": "en-US"},
            json={"email": member.json()["email"]},
        )
        assert reset_request.status_code == 202, reset_request.text
        reset_file = Path(reset_request.json()["filePath"])
        reset_document = reset_file.read_text(encoding="utf-8")
        token_match = re.search(r"#token=([^\"<]+)", reset_document)
        assert token_match is not None
        reset_password = "reset member password value"
        invalid_reset = client.post(
            "/api/v2/auth/password-reset/confirm",
            json={"token": "x" * 32, "newPassword": reset_password},
        )
        assert invalid_reset.status_code == 400
        reset_confirm = client.post(
            "/api/v2/auth/password-reset/confirm",
            json={"token": token_match.group(1), "newPassword": reset_password},
        )
        assert reset_confirm.status_code == 200, reset_confirm.text
        assert not reset_file.exists()
        with TestClient(create_app(settings)) as reset_client:
            reset_login = reset_client.post(
                "/api/v2/auth/login",
                json={
                    "email": member.json()["email"],
                    "password": reset_password,
                },
            )
            assert reset_login.status_code == 200, reset_login.text

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
        work_update = client.patch(
            f"/api/v2/catalog/works/{created.json()['id']}",
            json={
                "title": "Updated Architecture Test Book",
                "summary": "Updated through the v2 application use case",
                "metadata": {
                    "seriesName": "Integration Series",
                    "seriesIndex": 1,
                    "tags": ["integration"],
                },
            },
        )
        assert work_update.status_code == 200, work_update.text
        assert work_update.json()["title"] == "Updated Architecture Test Book"
        assert client.get(f"/api/v2/catalog/works/{created.json()['id']}").status_code == 200
        missing_catalog_id = uuid.uuid4()
        assert client.get(f"/api/v2/catalog/works/{missing_catalog_id}").status_code == 404
        assert (
            client.patch(
                f"/api/v2/catalog/works/{missing_catalog_id}",
                json={"title": "Missing Work"},
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v2/catalog/works/{missing_catalog_id}").status_code == 404
        series = client.get("/api/v2/catalog/series?pageSize=10")
        assert series.status_code == 200
        assert series.json()["items"][0]["name"] == "Integration Series"
        series_works = client.get(
            "/api/v2/catalog/works?seriesName=Integration%20Series&pageSize=10"
        )
        assert series_works.status_code == 200
        assert series_works.json()["total"] == 1
        assert client.get("/api/v2/catalog/facets").status_code == 200
        assert (
            client.delete(
                f"/api/v2/catalog/shelves/{shelf.json()['id']}/works/{created.json()['id']}"
            ).status_code
            == 204
        )
        assert (
            client.put(
                f"/api/v2/catalog/shelves/{shelf.json()['id']}/works/{created.json()['id']}"
            ).status_code
            == 204
        )
        shelf_update = client.patch(
            f"/api/v2/catalog/shelves/{shelf.json()['id']}",
            json={
                "name": "Updated Integration Shelf",
                "pinned": False,
                "bookIds": [created.json()["id"]],
            },
        )
        assert shelf_update.status_code == 200, shelf_update.text
        assert client.get(f"/api/v2/catalog/shelves/{missing_catalog_id}").status_code == 404
        assert (
            client.patch(
                f"/api/v2/catalog/shelves/{missing_catalog_id}",
                json={"name": "Missing Shelf"},
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"/api/v2/catalog/shelves/{missing_catalog_id}/works/{created.json()['id']}"
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v2/catalog/shelves/{missing_catalog_id}/works/{created.json()['id']}"
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v2/catalog/shelves/{missing_catalog_id}").status_code == 404
        categories = client.get("/api/v2/catalog/categories?kind=TAG&pageSize=10")
        assert categories.status_code == 200
        assert (
            client.patch(
                f"/api/v2/catalog/categories/{missing_catalog_id}",
                json={"name": "Missing Category"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v2/catalog/categories/merge",
                json={
                    "kind": "TAG",
                    "targetId": str(missing_catalog_id),
                    "sourceIds": [str(uuid.uuid4())],
                },
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v2/catalog/categories/{missing_catalog_id}").status_code == 404

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
        assert client.get("/api/v2/ingestion/conversions").status_code == 200
        folder_update = client.patch(
            f"/api/v2/ingestion/folders/{folder.json()['id']}",
            json={"recursive": False, "options": {"ignoreHidden": False}},
        )
        assert folder_update.status_code == 200, folder_update.text
        folder_scan = client.post(f"/api/v2/ingestion/folders/{folder.json()['id']}/scan")
        assert folder_scan.status_code == 202, folder_scan.text
        rescan = client.post("/api/v2/ingestion/imports/rescan")
        assert rescan.status_code == 202, rescan.text
        assert (
            client.post(f"/api/v2/ingestion/imports/{completed_jobs[0]['id']}/retry").status_code
            == 404
        )

        bootstrap = client.get(f"/api/v2/reading/editions/{edition_id}/bootstrap")
        assert bootstrap.status_code == 200, bootstrap.text
        assert bootstrap.json()["accountId"] == account_id
        assert len(bootstrap.json()["files"]) == 1
        missing_reading_id = uuid.uuid4()
        assert (
            client.get(f"/api/v2/reading/editions/{missing_reading_id}/bootstrap").status_code
            == 404
        )
        assert (
            client.get(f"/api/v2/reading/editions/{missing_reading_id}/resource").status_code == 404
        )
        assert (
            client.get(
                f"/api/v2/reading/editions/{edition_id}/resource",
                headers={"Range": "items=0-1"},
            ).status_code
            == 416
        )
        assert client.get(f"/api/v2/reading/files/{missing_reading_id}").status_code == 404
        assert (
            client.get(
                f"/api/v2/reading/files/{bootstrap.json()['target']['fileId']}",
                headers={"Range": "items=0-1"},
            ).status_code
            == 416
        )
        assert client.get(f"/api/v2/reading/volumes/{missing_reading_id}/pages").status_code == 404
        assert (
            client.get(f"/api/v2/reading/volumes/{missing_reading_id}/pages/0").status_code == 404
        )
        imported_detail = client.get(
            f"/api/v2/catalog/works/{bootstrap.json()['target']['workId']}"
        )
        assert imported_detail.status_code == 200
        assert (
            imported_detail.json()["editions"][0]["files"][0]["id"]
            == (bootstrap.json()["target"]["fileId"])
        )
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
        assert (
            client.get(
                f"/api/v2/reading/preferences?scope=edition&targetId={edition_id}"
            ).status_code
            == 200
        )
        assert client.get(f"/api/v2/reading/editions/{edition_id}/progress").status_code == 200
        progress_conflict = client.put(
            f"/api/v2/reading/editions/{edition_id}/progress",
            json={
                "deviceId": "integration-browser",
                "position": {"location": {"type": "epub", "progression": 0.75}},
                "percentage": 0.75,
                "expectedVersion": 999,
            },
        )
        assert progress_conflict.status_code == 409
        resource = client.get(f"/api/v2/reading/editions/{edition_id}/resource")
        assert resource.status_code == 200, resource.text
        partial_resource = client.get(
            f"/api/v2/reading/editions/{edition_id}/resource",
            headers={"Range": "bytes=0-3"},
        )
        assert partial_resource.status_code == 206, partial_resource.text
        file_partial = client.get(
            f"/api/v2/reading/files/{bootstrap.json()['target']['fileId']}",
            headers={"Range": "bytes=0-3"},
        )
        assert file_partial.status_code == 206, file_partial.text
        claim = client.post(
            f"/api/v2/reading/editions/{edition_id}/epub-locations/claim",
            json={
                "cacheVersion": 1,
                "contentFingerprint": "integration-fingerprint",
                "breakSize": 1024,
            },
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()["status"] == "claimed"
        lease_token = claim.json()["leaseToken"]
        wrong_lease = client.put(
            f"/api/v2/reading/editions/{edition_id}/epub-locations",
            json={
                "cacheVersion": 1,
                "contentFingerprint": "integration-fingerprint",
                "breakSize": 1024,
                "leaseToken": "x" * 32,
                "serialized": "[]",
            },
        )
        assert wrong_lease.status_code == 409
        saved_locations = client.put(
            f"/api/v2/reading/editions/{edition_id}/epub-locations",
            json={
                "cacheVersion": 1,
                "contentFingerprint": "integration-fingerprint",
                "breakSize": 1024,
                "leaseToken": lease_token,
                "serialized": '[{"cfi":"epubcfi(/6/2)"}]',
            },
        )
        assert saved_locations.status_code == 200, saved_locations.text
        ready_claim = client.post(
            f"/api/v2/reading/editions/{edition_id}/epub-locations/claim",
            json={
                "cacheVersion": 1,
                "contentFingerprint": "integration-fingerprint",
                "breakSize": 1024,
            },
        )
        assert ready_claim.json()["status"] == "ready"
        bookmark_id = bookmark.json()["id"]
        assert (
            client.delete(
                f"/api/v2/reading/editions/{edition_id}/bookmarks/{bookmark_id}"
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/v2/reading/editions/{edition_id}/bookmarks/{bookmark_id}"
            ).status_code
            == 404
        )

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
        provider_update = client.patch(
            f"/api/v2/metadata/providers/{provider.json()['id']}",
            json={"name": "Updated Integration Provider", "priority": 50},
        )
        assert provider_update.status_code == 200, provider_update.text
        metadata_container = build_container(settings)
        try:
            assert metadata_container.metadata_worker.run_once("metadata-worker")
            assert not metadata_container.metadata_worker.run_once("metadata-worker")
        finally:
            metadata_container.close()
        metadata_jobs = client.get("/api/v2/metadata/jobs?status=completed&pageSize=10")
        assert metadata_jobs.status_code == 200
        candidates = client.get(f"/api/v2/metadata/jobs/{metadata_job.json()['id']}/candidates")
        assert candidates.status_code == 200
        assert candidates.json()["total"] == 0
        assert client.get(f"/api/v2/metadata/jobs/{uuid.uuid4()}/candidates").status_code == 404

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
        source_update = client.patch(
            f"/api/v2/discovery/sources/{source.json()['id']}",
            json={"name": "Updated Integration Source", "baseUrl": "https://example.org/books/"},
        )
        assert source_update.status_code == 200, source_update.text
        disabled_search = client.post(
            f"/api/v2/discovery/sources/{source.json()['id']}/search",
            json={"query": "book"},
        )
        assert disabled_search.status_code == 404
        assert client.get("/api/v2/discovery/results").json()["total"] == 0
        assert client.get("/api/v2/discovery/downloads").json()["total"] == 0
        assert client.post(f"/api/v2/discovery/downloads/{uuid.uuid4()}").status_code == 404

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
                "security": "starttls",
            },
        )
        assert email_settings.status_code == 200, email_settings.text
        assert client.get("/api/v2/delivery/email/settings").status_code == 200
        email_status = client.get("/api/v2/delivery/email/status")
        assert email_status.status_code == 200
        assert email_status.json() == {
            "configured": True,
            "sender": "sender@example.com",
        }
        assert client.get("/api/v2/delivery/kindle/settings").status_code == 200
        kindle_job = client.post(
            "/api/v2/delivery/kindle/jobs",
            json={
                "fileId": bootstrap.json()["target"]["fileId"],
                "subject": "Integration delivery",
            },
        )
        assert kindle_job.status_code == 202, kindle_job.text
        delivery_jobs = client.get("/api/v2/delivery/kindle/jobs?status=queued&pageSize=10")
        assert delivery_jobs.status_code == 200
        assert delivery_jobs.json()["total"] == 1
        assert (
            client.delete(f"/api/v2/delivery/kindle/jobs/{kindle_job.json()['id']}").status_code
            == 204
        )
        assert (
            client.post(f"/api/v2/delivery/kindle/jobs/{kindle_job.json()['id']}/retry").status_code
            == 202
        )
        assert (
            client.delete(f"/api/v2/delivery/kindle/jobs/{kindle_job.json()['id']}").status_code
            == 204
        )

        settings_response = client.put(
            "/api/v2/operations/settings",
            json={"values": {"metadata.external.enabled": {"value": "true"}}},
        )
        assert settings_response.status_code == 200
        assert client.get("/api/v2/operations/events").json()["total"] >= 1
        backup = client.post("/api/v2/operations/backups")
        assert backup.status_code == 202, backup.text
        assert backup.json()["appVersion"] == "0.4.0"
        backup_id = backup.json()["id"]
        assert client.get("/api/v2/operations/backups").json()["total"] == 1
        assert client.get(f"/api/v2/operations/backups/{backup_id}").status_code == 200
        assert client.get(f"/api/v2/operations/backups/{backup_id}/download").status_code == 404
        assert client.post(f"/api/v2/operations/backups/{backup_id}/restore").status_code == 404
        assert client.get("/api/v2/operations/events?kind=backup.requested").status_code == 200
        assert client.get("/api/v2/reporting/dashboard").status_code == 200
        assert client.get("/api/v2/reporting/management").status_code == 200
        assert client.delete(f"/api/v2/operations/backups/{backup_id}").status_code == 204
        assert client.get(f"/api/v2/operations/backups/{backup_id}").status_code == 404
        assert client.delete(f"/api/v2/discovery/sources/{source.json()['id']}").status_code == 204
        assert client.delete(f"/api/v2/ingestion/folders/{folder.json()['id']}").status_code == 204
        assert client.delete(f"/api/v2/catalog/shelves/{shelf.json()['id']}").status_code == 204
        clear_finished = client.delete("/api/v2/ingestion/imports")
        assert clear_finished.status_code == 200
        assert clear_finished.json()["deleted"] >= 2
