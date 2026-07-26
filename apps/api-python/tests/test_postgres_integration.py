# ruff: noqa: S105

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from appv2.composition.api import create_app
from appv2.composition.container import build_container
from appv2.modules.ingestion.contracts import ImportRequest
from appv2.modules.ingestion.infrastructure.repositories import ingestion_uow_factory
from appv2.platform.config import Settings, get_settings
from appv2.platform.database import Database


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
                json={
                    "email": member.json()["email"],
                    "currentPassword": "correct horse battery staple",
                },
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
        cover = BytesIO()
        Image.new("RGB", (800, 1200), (255, 80, 40)).save(cover, format="PNG")
        cover_upload = client.post(
            f"/api/v2/catalog/works/{created.json()['id']}/cover/upload",
            files={"cover": ("cover.png", cover.getvalue(), "image/png")},
        )
        assert cover_upload.status_code == 200, cover_upload.text
        assert cover_upload.json()["coverUrl"].endswith("/cover")
        cover_response = client.get(
            f"/api/v2/catalog/works/{created.json()['id']}/cover?size=small"
        )
        assert cover_response.status_code == 200
        assert cover_response.headers["content-type"] == "image/webp"
        assert cover_response.headers["etag"]
        assert (
            client.post(
                f"/api/v2/catalog/works/{created.json()['id']}/cover/upload",
                files={"cover": ("invalid.txt", b"not-an-image", "text/plain")},
            ).status_code
            == 422
        )
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
        assert client.get(f"/api/v2/catalog/works/{missing_catalog_id}/cover").status_code == 404
        assert (
            client.post(
                f"/api/v2/catalog/works/{missing_catalog_id}/cover/upload",
                files={"cover": ("cover.png", cover.getvalue(), "image/png")},
            ).status_code
            == 404
        )
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
        duplicate_work = client.post(
            "/api/v2/catalog/works",
            json={
                "title": "Updated Architecture Test Book",
                "author": "Codex",
                "mediaType": "book",
            },
        )
        assert duplicate_work.status_code == 201, duplicate_work.text
        bulk_metadata = client.post(
            "/api/v2/catalog/works/bulk/metadata",
            json={
                "workIds": [created.json()["id"], duplicate_work.json()["id"]],
                "author": "Codex Updated",
                "seriesName": "Bulk Integration Series",
                "addTags": ["bulk"],
                "removeTags": ["integration"],
            },
        )
        assert bulk_metadata.status_code == 200, bulk_metadata.text
        assert bulk_metadata.json()["updated"] == 2
        preview_replace = client.post(
            "/api/v2/catalog/works/bulk/find-replace/preview",
            json={
                "workIds": [created.json()["id"], duplicate_work.json()["id"]],
                "field": "title",
                "find": "Architecture",
                "replacement": "Transactional",
            },
        )
        assert preview_replace.status_code == 200, preview_replace.text
        assert preview_replace.json()["changedWorks"] == 2
        apply_replace = client.post(
            "/api/v2/catalog/works/bulk/find-replace",
            json={
                "workIds": [created.json()["id"], duplicate_work.json()["id"]],
                "field": "title",
                "find": "Architecture",
                "replacement": "Transactional",
            },
        )
        assert apply_replace.status_code == 200, apply_replace.text
        assert apply_replace.json()["updated"] == 2
        assert (
            client.post(
                "/api/v2/catalog/works/bulk/find-replace/preview",
                json={
                    "workIds": [created.json()["id"]],
                    "field": "title",
                    "find": "[",
                    "replacement": "invalid",
                    "regex": True,
                },
            ).status_code
            == 422
        )
        bulk_shelf = client.post(
            f"/api/v2/catalog/shelves/{shelf.json()['id']}/works/bulk",
            json={
                "workIds": [duplicate_work.json()["id"], str(missing_catalog_id)],
                "present": True,
            },
        )
        assert bulk_shelf.status_code == 200, bulk_shelf.text
        assert bulk_shelf.json()["updated"] == 1
        assert bulk_shelf.json()["skipped"][0]["workId"] == str(missing_catalog_id)
        duplicates = client.get("/api/v2/catalog/duplicates")
        assert duplicates.status_code == 200, duplicates.text
        duplicate_group = next(
            group
            for group in duplicates.json()["items"]
            if {work["id"] for work in group["works"]}
            == {created.json()["id"], duplicate_work.json()["id"]}
        )
        assert duplicate_group["confidence"] == 0.98
        assert (
            client.post(
                "/api/v2/catalog/duplicates/merge",
                json={
                    "targetWorkId": created.json()["id"],
                    "sourceWorkIds": [created.json()["id"]],
                },
            ).status_code
            == 422
        )
        merge = client.post(
            "/api/v2/catalog/duplicates/merge",
            json={
                "targetWorkId": created.json()["id"],
                "sourceWorkIds": [duplicate_work.json()["id"]],
            },
        )
        assert merge.status_code == 200, merge.text
        assert merge.json()["affectedWorks"] == 1
        assert merge.json()["undoAvailable"] is True
        assert (
            client.get(f"/api/v2/catalog/works/{duplicate_work.json()['id']}").json()["status"]
            == "archived"
        )
        undo = client.post(
            f"/api/v2/catalog/operations/{merge.json()['id']}/undo",
        )
        assert undo.status_code == 200, undo.text
        assert undo.json()["status"] == "reverted"
        assert (
            client.get(f"/api/v2/catalog/works/{duplicate_work.json()['id']}").json()["status"]
            == "active"
        )
        assert (
            client.post(
                f"/api/v2/catalog/operations/{merge.json()['id']}/undo",
            ).status_code
            == 404
        )
        bulk_cover = client.post(
            "/api/v2/catalog/works/bulk/cover",
            files=[
                ("workIds", (None, created.json()["id"])),
                ("workIds", (None, duplicate_work.json()["id"])),
                ("cover", ("shared-cover.png", cover.getvalue(), "image/png")),
            ],
        )
        assert bulk_cover.status_code == 200, bulk_cover.text
        assert bulk_cover.json()["updated"] == 2
        assert (
            client.get(f"/api/v2/catalog/works/{duplicate_work.json()['id']}/cover").status_code
            == 200
        )
        assert (
            client.post(
                "/api/v2/catalog/works/bulk/cover",
                files=[
                    ("workIds", (None, duplicate_work.json()["id"])),
                    ("cover", ("invalid.txt", b"not-an-image", "text/plain")),
                ],
            ).status_code
            == 422
        )
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
        invalid_folder = client.post(
            "/api/v2/ingestion/folders",
            json={
                "path": str(tmp_path / "outside"),
                "recursive": True,
                "options": {},
            },
        )
        assert invalid_folder.status_code == 422, invalid_folder.text
        assert invalid_folder.headers["content-type"].startswith("application/problem+json")
        assert invalid_folder.json()["code"] == "INVALID_MONITOR_PATH"
        invalid_tree = client.get(
            "/api/v2/ingestion/folders/tree",
            params={"path": str(tmp_path)},
        )
        assert invalid_tree.status_code == 422, invalid_tree.text
        assert invalid_tree.json()["code"] == "INVALID_MONITOR_PATH"
        invalid_scan = client.post(
            "/api/v2/ingestion/imports/scan-directory",
            json={"path": str(tmp_path)},
        )
        assert invalid_scan.status_code == 422, invalid_scan.text
        assert invalid_scan.json()["code"] == "INVALID_MONITOR_PATH"
        folder = client.post(
            "/api/v2/ingestion/folders",
            json={
                "path": str(monitored),
                "recursive": True,
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
        queues = client.get("/api/v2/operations/queues")
        assert queues.status_code == 200, queues.text
        ingestion_queue = next(
            item for item in queues.json()["items"] if item["name"] == "ingestion"
        )
        assert ingestion_queue["counts"]["queued"] == 2
        paused_queue = client.patch(
            "/api/v2/operations/queues/ingestion",
            json={"enabled": False},
        )
        assert paused_queue.status_code == 200, paused_queue.text
        assert paused_queue.json()["status"] == "paused"
        resumed_queue = client.patch(
            "/api/v2/operations/queues/ingestion",
            json={"enabled": True},
        )
        assert resumed_queue.status_code == 200, resumed_queue.text
        assert resumed_queue.json()["enabled"] is True
        assert (
            client.patch(
                "/api/v2/operations/queues/unknown",
                json={"enabled": False},
            ).status_code
            == 404
        )

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
        edition_id = completed_jobs[0]["resultEditionId"]
        delete_regression_source = monitored / "Delete Regression.txt"
        delete_regression_source.write_text("delete regression", encoding="utf-8")
        delete_regression_import = client.post(
            "/api/v2/ingestion/imports",
            json={"sourcePath": str(delete_regression_source)},
            headers={"Idempotency-Key": f"integration-delete-{uuid.uuid4().hex}"},
        )
        assert delete_regression_import.status_code == 202, delete_regression_import.text
        delete_regression_container = build_container(settings)
        try:
            assert delete_regression_container.ingestion_worker.run_once(
                "integration-delete-worker"
            )
        finally:
            delete_regression_container.close()
        delete_regression_job = client.get(
            f"/api/v2/ingestion/imports/{delete_regression_import.json()['id']}"
        )
        assert delete_regression_job.status_code == 200, delete_regression_job.text
        deleted_work_id = delete_regression_job.json()["job"]["resultWorkId"]
        assert deleted_work_id
        assert (
            client.delete(f"/api/v2/catalog/works/{deleted_work_id}").status_code
            == 204
        )
        assert delete_regression_source.exists()
        assert client.get(f"/api/v2/catalog/works/{deleted_work_id}").status_code == 404
        deleted_job_history = client.get(
            f"/api/v2/ingestion/imports/{delete_regression_import.json()['id']}"
        )
        assert deleted_job_history.json()["job"]["status"] == "completed"
        assert deleted_job_history.json()["job"]["resultWorkId"] is None
        reimport = client.post(
            "/api/v2/ingestion/imports",
            json={"sourcePath": str(delete_regression_source)},
            headers={"Idempotency-Key": f"integration-reimport-{uuid.uuid4().hex}"},
        )
        assert reimport.status_code == 202, reimport.text
        reimport_container = build_container(settings)
        try:
            assert reimport_container.ingestion_worker.run_once(
                "integration-reimport-worker"
            )
        finally:
            reimport_container.close()
        reimported_job = client.get(f"/api/v2/ingestion/imports/{reimport.json()['id']}")
        assert reimported_job.status_code == 200, reimported_job.text
        assert reimported_job.json()["job"]["status"] == "completed"
        reimported_work_id = reimported_job.json()["job"]["resultWorkId"]
        assert reimported_work_id and reimported_work_id != deleted_work_id
        restored_library = client.get(
            "/api/v2/reporting/library",
            params={"query": "Delete Regression"},
        )
        assert reimported_work_id in {
            item["id"] for item in restored_library.json()["items"]
        }
        assert (
            client.delete(
                f"/api/v2/catalog/works/{reimported_work_id}",
                params={"deleteSource": "true"},
            ).status_code
            == 204
        )
        assert not delete_regression_source.exists()
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
        assert len(bootstrap.json()["files"]) == 2
        assert any(file["mediaType"] == "text/plain" for file in bootstrap.json()["files"])
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
        imported_work_id = bootstrap.json()["target"]["workId"]
        edition_update = client.patch(
            f"/api/v2/catalog/works/{imported_work_id}/editions/{edition_id}",
            json={
                "versionName": "Integration Text Edition",
                "publisher": "Shuku Test Press",
                "publishedAt": "2026-07-25",
                "language": "en-US",
                "identifier": "integration-edition",
                "description": "Edition metadata contract",
            },
        )
        assert edition_update.status_code == 200, edition_update.text
        assert edition_update.json()["title"] == "Integration Text Edition"
        assert edition_update.json()["metadata"]["publisher"] == "Shuku Test Press"
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/editions/{edition_id}/primary"
            ).status_code
            == 204
        )
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/editions/{edition_id}/split",
                json={
                    "title": "Cannot Split Only Edition",
                    "author": "Integration",
                    "copyShelves": True,
                },
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/v2/catalog/works/{imported_work_id}/editions/{missing_reading_id}",
                json={"versionName": "Missing Edition"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/editions/{missing_reading_id}/primary"
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/volumes/{missing_reading_id}/move",
                json={"direction": "up"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/volumes/{missing_reading_id}/move-to",
                json={"targetEditionId": edition_id},
            ).status_code
            == 404
        )
        conversion = client.post(
            "/api/v2/ingestion/conversions",
            json={"editionId": edition_id},
        )
        assert conversion.status_code == 422, conversion.text
        assert (
            client.post(
                "/api/v2/ingestion/conversions",
                json={"editionId": str(missing_reading_id)},
            ).status_code
            == 404
        )
        secondary_edition_id = uuid.uuid4()
        first_volume_id = uuid.uuid4()
        second_volume_id = uuid.uuid4()
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO catalog.editions
                        (id, work_id, title, format, language, is_primary, metadata,
                         created_at, updated_at)
                    VALUES
                        (:id, :work_id, :title, 'txt', 'en-US', false,
                         CAST(:metadata AS jsonb), :created_at, :updated_at)
                    """
                ),
                {
                    "id": secondary_edition_id,
                    "work_id": uuid.UUID(imported_work_id),
                    "title": "Secondary Integration Edition",
                    "metadata": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO catalog.volumes
                        (id, edition_id, title, sort_order, page_count, duration_ms,
                         created_at, updated_at)
                    VALUES
                        (:first_id, :edition_id, 'First volume', 0, 10, NULL,
                         :created_at, :updated_at),
                        (:second_id, :edition_id, 'Second volume', 1, 20, NULL,
                         :created_at, :updated_at)
                    """
                ),
                {
                    "first_id": first_volume_id,
                    "second_id": second_volume_id,
                    "edition_id": secondary_edition_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/editions/{secondary_edition_id}/primary"
            ).status_code
            == 204
        )
        primary_detail = client.get(f"/api/v2/catalog/works/{imported_work_id}").json()
        assert next(
            edition
            for edition in primary_detail["editions"]
            if edition["id"] == str(secondary_edition_id)
        )["primary"]
        assert (
            client.post(
                f"/api/v2/catalog/works/{imported_work_id}/volumes/{first_volume_id}/move",
                json={"direction": "down"},
            ).status_code
            == 204
        )
        reordered_detail = client.get(f"/api/v2/catalog/works/{imported_work_id}").json()
        reordered_volumes = next(
            edition["volumes"]
            for edition in reordered_detail["editions"]
            if edition["id"] == str(secondary_edition_id)
        )
        assert [volume["id"] for volume in reordered_volumes] == [
            str(second_volume_id),
            str(first_volume_id),
        ]
        moved_volume = client.post(
            f"/api/v2/catalog/works/{imported_work_id}/volumes/{first_volume_id}/move-to",
            json={"targetEditionId": edition_id},
        )
        assert moved_volume.status_code == 200, moved_volume.text
        assert moved_volume.json()["transferMode"] == "MERGED_VOLUME"
        assert (
            client.put(
                f"/api/v2/catalog/shelves/{shelf.json()['id']}/works/{imported_work_id}"
            ).status_code
            == 204
        )
        split = client.post(
            f"/api/v2/catalog/works/{imported_work_id}/editions/{secondary_edition_id}/split",
            json={
                "title": "Split Integration Work",
                "author": "Integration",
                "copyShelves": True,
            },
        )
        assert split.status_code == 201, split.text
        split_work_id = split.json()["newWorkId"]
        split_detail = client.get(f"/api/v2/catalog/works/{split_work_id}")
        assert split_detail.status_code == 200
        assert split_detail.json()["editions"][0]["id"] == str(secondary_edition_id)
        split_shelf = client.get(f"/api/v2/catalog/shelves/{shelf.json()['id']}")
        assert split_shelf.status_code == 200
        assert split_work_id in split_shelf.json()["bookIds"]
        progress = client.put(
            f"/api/v2/reading/editions/{edition_id}/progress",
            json={
                "deviceId": "integration-browser",
                "position": {"location": {"type": "epub", "progression": 0.5}},
                "percentage": 0.5,
            },
        )
        assert progress.status_code == 200, progress.text
        reading_library = client.get(
            "/api/v2/reporting/library",
            params={
                "readingStatus": "READING",
                "filters": json.dumps(
                    {
                        "combinator": "ALL",
                        "conditions": [
                            {
                                "field": "title",
                                "operator": "contains",
                                "value": imported_detail.json()["title"],
                            }
                        ],
                    }
                ),
            },
        )
        assert reading_library.status_code == 200, reading_library.text
        assert imported_work_id in {item["id"] for item in reading_library.json()["items"]}
        filter_schema = client.get("/api/v2/reporting/library/filter-schema")
        assert filter_schema.status_code == 200, filter_schema.text
        assert {
            "title",
            "readingStatus",
            "progress",
            "shelf",
        }.issubset({field["key"] for field in filter_schema.json()["fields"]})
        assert (
            client.get(
                "/api/v2/reporting/library",
                params={"filters": '{"combinator":"ALL","conditions":[{"field":"unknown"}]}'},
            ).status_code
            == 422
        )
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
        bulk_finished = client.post(
            "/api/v2/reading/progress/bulk",
            json={
                "workIds": [
                    imported_work_id,
                    created.json()["id"],
                    str(missing_reading_id),
                ],
                "status": "FINISHED",
            },
        )
        assert bulk_finished.status_code == 200, bulk_finished.text
        assert bulk_finished.json()["updated"] == 1
        assert bulk_finished.json()["changedValues"] == 1
        assert len(bulk_finished.json()["skipped"]) == 2
        finished_progress = client.get(f"/api/v2/reading/editions/{edition_id}/progress")
        assert finished_progress.json()["percentage"] == 1
        assert finished_progress.json()["position"] == {"kind": "completed"}
        finished_library = client.get(
            "/api/v2/reporting/library",
            params={"readingStatus": "FINISHED", "sort": "recent_read"},
        )
        assert finished_library.status_code == 200, finished_library.text
        assert imported_work_id in {item["id"] for item in finished_library.json()["items"]}
        bulk_unread = client.post(
            "/api/v2/reading/progress/bulk",
            json={
                "workIds": [imported_work_id],
                "status": "UNREAD",
            },
        )
        assert bulk_unread.status_code == 200, bulk_unread.text
        assert bulk_unread.json()["changedValues"] == 1
        assert client.get(f"/api/v2/reading/editions/{edition_id}/progress").json() is None
        unread_library = client.get(
            "/api/v2/reporting/library",
            params={"readingStatus": "UNREAD"},
        )
        assert unread_library.status_code == 200, unread_library.text
        assert imported_work_id in {item["id"] for item in unread_library.json()["items"]}
        series_library = client.get(
            "/api/v2/reporting/library",
            params={"seriesName": "Bulk Integration Series"},
        )
        assert series_library.status_code == 200, series_library.text
        assert created.json()["id"] in {item["id"] for item in series_library.json()["items"]}
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
        assert (
            client.post(
                "/api/v2/metadata/jobs",
                json={"workId": str(uuid.uuid4()), "query": "Missing work"},
            ).status_code
            == 404
        )
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
        metadata_job_id = metadata_job.json()["id"]
        assert client.get(f"/api/v2/metadata/jobs/{metadata_job_id}").status_code == 200
        candidates = client.get(f"/api/v2/metadata/jobs/{metadata_job.json()['id']}/candidates")
        assert candidates.status_code == 200
        assert candidates.json()["total"] == 0
        assert client.get(f"/api/v2/metadata/jobs/{uuid.uuid4()}/candidates").status_code == 404
        candidate_id = uuid.uuid4()
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO metadata.candidates (
                        id, job_id, provider_id, external_id, title, author,
                        confidence, cover_url, raw_payload, created_at, updated_at
                    ) VALUES (
                        :id, :job_id, :provider_id, :external_id, :title, :author,
                        :confidence, NULL, CAST(:raw_payload AS jsonb), :now, :now
                    )
                    """
                ),
                {
                    "id": candidate_id,
                    "job_id": uuid.UUID(metadata_job_id),
                    "provider_id": uuid.UUID(provider.json()["id"]),
                    "external_id": "integration-candidate",
                    "title": "Applied Candidate Title",
                    "author": "Applied Candidate Author",
                    "confidence": 0.95,
                    "raw_payload": '{"publisher":"Test Publisher"}',
                    "now": now,
                },
            )
        candidates = client.get(f"/api/v2/metadata/jobs/{metadata_job_id}/candidates")
        assert candidates.json()["items"][0]["id"] == str(candidate_id)
        assert (
            client.post(
                f"/api/v2/metadata/jobs/{metadata_job_id}/candidates/{uuid.uuid4()}/apply",
                json={"fields": ["title"]},
            ).status_code
            == 404
        )
        applied = client.post(
            f"/api/v2/metadata/jobs/{metadata_job_id}/candidates/{candidate_id}/apply",
            json={"fields": ["title", "author", "publisher"]},
        )
        assert applied.status_code == 204, applied.text
        updated_work = client.get(f"/api/v2/catalog/works/{created.json()['id']}")
        assert updated_work.json()["title"] == "Applied Candidate Title"
        assert updated_work.json()["metadata"]["publisher"] == "Test Publisher"
        retry = client.post(f"/api/v2/metadata/jobs/{metadata_job_id}/retry")
        assert retry.status_code == 202
        assert retry.json()["status"] == "queued"
        assert client.delete(f"/api/v2/metadata/jobs/{metadata_job_id}").status_code == 204
        assert client.get(f"/api/v2/metadata/jobs/{metadata_job_id}").status_code == 404
        missing_metadata_job_id = uuid.uuid4()
        assert (
            client.post(f"/api/v2/metadata/jobs/{missing_metadata_job_id}/retry").status_code == 404
        )
        assert client.delete(f"/api/v2/metadata/jobs/{missing_metadata_job_id}").status_code == 404
        running_job = client.post(
            "/api/v2/metadata/jobs",
            headers={"Idempotency-Key": uuid.uuid4().hex},
            json={"workId": created.json()["id"], "query": "Running metadata job"},
        )
        running_job_id = running_job.json()["id"]
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE metadata.jobs SET status = 'running' WHERE id = :id"),
                {"id": uuid.UUID(running_job_id)},
            )
        assert client.post(f"/api/v2/metadata/jobs/{running_job_id}/retry").status_code == 409
        assert client.delete(f"/api/v2/metadata/jobs/{running_job_id}").status_code == 409
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE metadata.jobs SET status = 'failed' WHERE id = :id"),
                {"id": uuid.UUID(running_job_id)},
            )
        assert client.delete(f"/api/v2/metadata/jobs/{running_job_id}").status_code == 204

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
        log_settings = client.get("/api/v2/operations/log-settings")
        assert log_settings.status_code == 200
        assert log_settings.json()["maxBytes"] == 5 * 1024 * 1024
        saved_log_settings = client.put(
            "/api/v2/operations/log-settings",
            json={"maxBytes": 1024 * 1024},
        )
        assert saved_log_settings.status_code == 200, saved_log_settings.text
        assert saved_log_settings.json()["maxBytes"] == 1024 * 1024
        cleared_events = client.delete("/api/v2/operations/events")
        assert cleared_events.status_code == 200
        assert cleared_events.json()["deleted"] >= 1
        backup = client.post("/api/v2/operations/backups")
        assert backup.status_code == 202, backup.text
        assert backup.json()["appVersion"] == "0.4.0"
        backup_id = backup.json()["id"]
        assert client.get("/api/v2/operations/backups").json()["total"] == 1
        assert client.get(f"/api/v2/operations/backups/{backup_id}").status_code == 200
        assert client.get(f"/api/v2/operations/backups/{backup_id}/download").status_code == 404
        assert client.post(f"/api/v2/operations/backups/{backup_id}/restore").status_code == 404
        restore_request_id = uuid.uuid4().hex
        restore_backup_id = uuid.uuid4()
        settings.control_root.mkdir(parents=True, exist_ok=True)
        (settings.control_root / f"restore-{restore_request_id}.result.json").write_text(
            json.dumps(
                {
                    "requestId": restore_request_id,
                    "backupId": str(restore_backup_id),
                    "status": "completed",
                    "detail": None,
                    "completedAt": datetime.now(UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        restore_status = client.get(f"/api/v2/operations/restores/{restore_request_id}")
        assert restore_status.status_code == 200
        assert restore_status.json()["status"] == "completed"
        assert restore_status.json()["backupId"] == str(restore_backup_id)
        assert client.get(f"/api/v2/operations/restores/{uuid.uuid4().hex}").status_code == 404
        assert client.get("/api/v2/operations/restores/not-valid").status_code == 422
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


@pytest.mark.postgres
def test_ingestion_queue_skip_locked_recovery_cancellation_and_outbox(
    tmp_path: Path,
) -> None:
    database_url = os.getenv("APPV2_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("APPV2_TEST_DATABASE_URL is not configured")
    backend_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(backend_root / "alembic-v2.ini"), "head")
    database = Database(database_url)
    uow_factory = ingestion_uow_factory(database.session_factory)
    try:
        for index in range(2):
            with uow_factory() as uow:
                uow.ingestion.enqueue(
                    ImportRequest(
                        source_path=str(tmp_path / f"queue-{index}.epub"),
                        requested_by=None,
                        idempotency_key=f"pg-queue-{uuid.uuid4()}",
                        origin="watch",
                        triggered_by="system",
                    )
                )
                uow.commit()

        now = datetime.now(UTC)
        with uow_factory() as first_uow:
            first = first_uow.ingestion.claim_next(
                worker_id="worker-a",
                now=now,
                lease_until=now - timedelta(seconds=1),
            )
            assert first is not None
            with uow_factory() as second_uow:
                second = second_uow.ingestion.claim_next(
                    worker_id="worker-b",
                    now=now,
                    lease_until=now + timedelta(seconds=30),
                )
                assert second is not None
                assert second.id != first.id
                second_uow.commit()
            first_uow.commit()

        with uow_factory() as recovery_uow:
            recovered = recovery_uow.ingestion.claim_next(
                worker_id="worker-c",
                now=now + timedelta(seconds=1),
                lease_until=now + timedelta(seconds=30),
            )
            assert recovered is not None
            assert recovered.id == first.id
            assert recovered.attempt == 2
            recovery_uow.commit()

        with uow_factory() as stale_uow:
            assert not stale_uow.ingestion.complete(
                recovered.id,
                worker_id="worker-a",
                work_id=uuid.uuid4(),
                edition_id=uuid.uuid4(),
                volume_ids=(),
            )
            assert stale_uow.ingestion.cancel(recovered.id)
            assert not stale_uow.ingestion.fail(
                recovered.id,
                worker_id="worker-c",
                error_code="IMPORT_FAILED",
                error_detail="cancel won the race",
                retryable=True,
                retry_at=now + timedelta(seconds=5),
            )
            assert stale_uow.ingestion.acknowledge_cancellation(
                recovered.id,
                worker_id="worker-c",
            )
            stale_uow.commit()

        work_id = uuid.uuid4()
        edition_id = uuid.uuid4()
        with uow_factory() as completion_uow:
            assert completion_uow.ingestion.complete(
                second.id,
                worker_id="worker-b",
                work_id=work_id,
                edition_id=edition_id,
                volume_ids=(),
            )
            completion_uow.commit()
        with uow_factory() as verification_uow:
            cancelled = verification_uow.ingestion.get_job(recovered.id)
            completed = verification_uow.ingestion.get_job(second.id)
            assert cancelled is not None and cancelled.status == "cancelled"
            assert completed is not None and completed.status == "completed"
        with database.engine.connect() as connection:
            event = connection.execute(
                text(
                    """
                    SELECT event_type, aggregate_id
                    FROM ingestion.outbox
                    WHERE idempotency_key = :idempotency_key
                    """
                ),
                {"idempotency_key": f"import.completed:{second.id}"},
            ).one()
            assert event.event_type == "import.completed"
            assert event.aggregate_id == work_id
    finally:
        database.dispose()
