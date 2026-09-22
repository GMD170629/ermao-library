"""Restore preflight failures preserve their actual I/O/programming cause."""

import errno

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.settings import SystemEvent
from app.modules.backup.application.restore import BackupRecordValidationError
from app.modules.backup.infrastructure import archive


@pytest.mark.parametrize("kind", ["io", "unknown_value", "known_record"])
def test_restore_preflight_does_not_misclassify_infrastructure_failures(tmp_path, monkeypatch, caplog, kind):
    settings = Settings(storage_root=str(tmp_path / "storage"), secure_cookies=False, download_queue_enabled=False, kindle_send_queue_enabled=False)
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    original = (
        OSError(errno.EIO, "temporary database I/O failed", "/private/restore-validation/database.sqlite")
        if kind == "io" else ValueError("restore writer invariant failed")
        if kind == "unknown_value" else BackupRecordValidationError("BACKUP_FIELD_TYPE_INVALID:User.id")
    )
    original_apply = archive.SqlAlchemyBackupRestoreWriter.apply
    observed_temporary_database = []

    def fail_preflight(writer, plan):
        # Exercise the real temporary-database preflight and request mapping;
        # the live restore must never start after failed validation execution.
        observed_temporary_database.append(plan.kind)
        raise original

    app = create_app(settings, session_factory=factory)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            setup = client.post("/api/auth/setup", json={"name": "Restore admin", "email": "restore-admin@example.com", "password": "restore-password"})
            assert setup.status_code == 201
            created = client.post("/api/backups")
            assert created.status_code == 201, created.text
            backup_id = created.json()["data"]["backup"]["id"]
            monkeypatch.setattr(archive.SqlAlchemyBackupRestoreWriter, "apply", fail_preflight)
            response = client.post(f"/api/backups/{backup_id}/restore")
            monkeypatch.setattr(archive.SqlAlchemyBackupRestoreWriter, "apply", original_apply)
            assert response.status_code == (400 if kind == "known_record" else 500), response.text
            assert response.json()["error"]["code"] == ("BACKUP_CONTENT_INVALID" if kind == "known_record" else "INTERNAL_ERROR")
            assert observed_temporary_database == ["database"]
            assert client.get("/api/auth/me").status_code == 200
        with factory() as db:
            failure = db.get(SystemEvent, response.headers["X-Error-Id"])
            assert failure is not None
            facts = failure.metadata_json["diagnostics"]["directException"]
            assert facts["type"].endswith(type(original).__name__)
            if kind == "io":
                assert facts["errno"] == errno.EIO
                assert facts["errorName"] == "EIO"
            assert failure.id in caplog.text
            assert failure.metadata_json["requestId"] == response.headers["X-Request-Id"]
            matching = db.scalars(select(SystemEvent).where(SystemEvent.id == failure.id)).all()
            assert len(matching) == 1
        assert "/private/restore-validation" not in caplog.text + response.text
    finally:
        engine.dispose()
