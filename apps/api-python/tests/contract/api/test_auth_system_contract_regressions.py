from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.import_pipeline import ImportTask
from app.models.settings import MonitorFolder


def _login_system_manager(client: TestClient, db: Session) -> User:
    user = User(
        email="system-contract@example.com",
        name="System contract",
        password_hash=hash_password("SystemContract123!"),
        role="admin",
        can_manage_system=True,
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "system-contract@example.com",
            "password": "SystemContract123!",
        },
    )
    assert response.status_code == 200
    return user


def test_dashboard_system_status_accepts_current_folder_and_import_task_rows(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login_system_manager(client, db_session)
    monitored_directory = tmp_path / "comic-library"
    monitored_directory.mkdir()
    folder = MonitorFolder(
        name="漫画目录",
        root_path=str(monitored_directory),
        enabled=True,
        media_kind_policy="COMIC",
        ignore_patterns=None,
        ignore_hidden=True,
        min_file_size_bytes=10240,
        description="dashboard contract",
    )
    db_session.add(folder)
    db_session.flush()
    task = ImportTask(
        id="dashboard-contract-task",
        monitor_folder_id=folder.id,
        media_kind_policy="COMIC",
        origin="WATCHER",
        status="COMPLETED",
        original_name="第一卷.cbz",
        requested_title="第一卷",
        requested_author="作者",
        recognized_metadata={
            "title": "第一卷",
            "source": "PATH",
        },
        source_path=str(monitored_directory / "第一卷.cbz"),
        source_key="dashboard-contract-source-key",
        content_hash="dashboard-contract-content-hash",
        task_kind="FILE",
        progress=100,
        processed_asset_count=1,
    )
    db_session.add(task)
    db_session.commit()

    response = client.get("/api/dashboard/system-status")

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["enabledMonitorFolders"][0]["mediaKindPolicy"] == "COMIC"
    latest = payload["latestImportTask"]
    assert latest["id"] == task.id
    assert latest["mediaKindPolicy"] == "COMIC"
    assert latest["recognizedMetadata"] == {
        "title": "第一卷",
        "source": "PATH",
    }
    assert latest["sourceKey"] == "dashboard-contract-source-key"


def test_log_settings_openapi_declares_typed_request_body(
    client: TestClient,
) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/system/log-settings"][
        "put"
    ]

    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/UpdateLogSettingsRequest")
