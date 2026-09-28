import io
import json
import zipfile
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.settings import SystemSetting
from app.modules.backup.infrastructure import archive as backup_archive


@pytest.fixture
def backup_client(tmp_path):
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(settings, session_factory=factory)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/api/auth/setup",
                    json={
                        "name": "Backup admin",
                        "email": "backup@example.com",
                        "password": "backup-password",
                    },
                ).status_code
                == 201
            )
            yield client
    finally:
        engine.dispose()


def test_uploaded_copies_have_independent_identity_and_restore(backup_client):
    client = backup_client
    created = client.post("/api/backups").json()["data"]["backup"]
    payload = client.get(f"/api/backups/{created['id']}/download").content
    copies = []
    for name in ("我的备份.zip", "我的备份.zip"):
        response = client.post(
            "/api/backups/upload", files={"file": (name, payload, "application/zip")}
        )
        assert response.status_code == 201, response.text
        copies.append(response.json()["data"]["backup"])
    assert [item["filename"] for item in copies] == [
        "我的备份.zip",
        "我的备份（1）.zip",
    ]
    assert len({created["id"], *(item["id"] for item in copies)}) == 3
    for item in copies:
        url = f"/api/backups/{quote(item['id'])}"
        assert client.get(url + "/download").content == payload
        result = client.post(url + "/restore")
        assert result.status_code == 200, result.text
        assert result.json()["data"]["id"] == item["id"]
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "backup@example.com", "password": "backup-password"},
            ).status_code
            == 200
        )
    assert client.delete(f"/api/backups/{quote(copies[0]['id'])}").json()["data"][
        "deleted"
    ]
    remaining = client.get("/api/backups").json()["data"]["backups"]
    assert {item["id"] for item in remaining} == {created["id"], copies[1]["id"]}


def test_incompatible_and_broken_uploads_are_saved_but_restore_is_rejected(
    backup_client,
):
    client = backup_client
    created = client.post("/api/backups").json()["data"]["backup"]
    payload = client.get(f"/api/backups/{created['id']}/download").content
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(payload)) as original,
        zipfile.ZipFile(output, "w") as modified,
    ):
        for name in original.namelist():
            content = original.read(name)
            if name == "metadata.json":
                metadata = json.loads(content)
                metadata["databaseRevision"] = "old-revision"
                content = json.dumps(metadata).encode()
            modified.writestr(name, content)
    for filename, data, code in [
        ("old.zip", output.getvalue(), "BACKUP_DATABASE_MISMATCH"),
        ("broken.zip", b"broken", "BACKUP_ZIP_INVALID"),
    ]:
        response = client.post("/api/backups/upload", files={"file": (filename, data)})
        assert response.status_code == 201, response.text
        backup = response.json()["data"]["backup"]
        assert backup["compatibility"]["problem"]["code"] == code
        response = client.post(f"/api/backups/{backup['id']}/restore")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == code
        assert response.json()["error"]["params"]["messageEn"]
        assert client.get("/api/auth/me").status_code == 200
    assert len(client.get("/api/backups").json()["data"]["backups"]) == 3


def test_upload_requires_authentication(backup_client):
    backup_client.cookies.clear()
    response = backup_client.post(
        "/api/backups/upload", files={"file": ("backup.zip", b"data")}
    )
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("invalid", ["missing", "duplicate"])
def test_real_database_constraints_are_explained_without_record_values(
    backup_client, invalid
):
    client = backup_client
    created = client.post("/api/backups").json()["data"]["backup"]
    data = client.get(f"/api/backups/{created['id']}/download").content
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as original,
        zipfile.ZipFile(output, "w") as modified,
    ):
        for name in original.namelist():
            content = original.read(name)
            if name == "database-export.json":
                exported = json.loads(content)
                if invalid == "missing":
                    exported["users"][0].pop("email")
                else:
                    exported["users"].append(
                        {**exported["users"][0], "id": "duplicate-email-user"}
                    )
                content = json.dumps(exported).encode()
            modified.writestr(name, content)
    uploaded = client.post(
        "/api/backups/upload",
        files={"file": ("invalid-records.zip", output.getvalue())},
    ).json()["data"]["backup"]
    assert uploaded["compatibility"]["status"] == "compatible"
    response = client.post(f"/api/backups/{uploaded['id']}/restore")
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == (
        "BACKUP_REQUIRED_FIELD" if invalid == "missing" else "BACKUP_UNIQUE_CONSTRAINT"
    )
    assert "User.email" in error["message"]
    assert "backup@example.com" not in response.text
    assert "INSERT" not in response.text
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("recovery_fails", [False, True])
def test_live_restore_failure_preserves_data_and_reports_recovery(
    backup_client, tmp_path, monkeypatch, caplog, recovery_fails
):
    client = backup_client
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(SystemSetting(key="backup.sentinel", value="archived"))
        db.commit()
    created = client.post("/api/backups").json()["data"]["backup"]
    with factory() as db:
        db.get(SystemSetting, "backup.sentinel").value = "live"
        db.commit()
    original = backup_archive.SqlAlchemyBackupRestoreWriter.apply

    def fail_live_write(writer, plan):
        if plan.kind == "database" and writer._db.get_bind().url.database == str(
            settings.database_path
        ):
            original(writer, plan)
            raise OSError(5, "live restore I/O failed")
        if (
            recovery_fails
            and plan.kind == "maintenance"
            and plan.maintenance_change.setting_value is None
        ):
            raise OSError(13, "maintenance recovery permission denied")
        original(writer, plan)

    monkeypatch.setattr(
        backup_archive.SqlAlchemyBackupRestoreWriter, "apply", fail_live_write
    )
    try:
        response = client.post(f"/api/backups/{created['id']}/restore")
        assert response.status_code == 500, response.text
        error = response.json()["error"]
        assert error["code"] == (
            "BACKUP_RECOVERY_FAILED" if recovery_fails else "BACKUP_IO_ERROR"
        )
        assert "live restore I/O failed" in error["message"]
        assert "live restore I/O failed" in caplog.text
        if recovery_fails:
            assert "Permission denied" in error["params"]["messageEn"]
            assert "maintenance recovery permission denied" in caplog.text
        with factory() as db:
            assert db.get(SystemSetting, "backup.sentinel").value == "live"
    finally:
        engine.dispose()
