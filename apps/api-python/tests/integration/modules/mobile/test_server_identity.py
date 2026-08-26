from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.runner import apply_schema
from app.db.sqlite import create_sqlite_engine
from app.models.settings import SystemSetting
from app.modules.backup.infrastructure.archive import create_backup, restore_backup
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY


def _read_server_identity(db: Session) -> str | None:
    return db.scalar(
        select(SystemSetting.value).where(
            SystemSetting.key == SERVER_IDENTITY_SETTING_KEY
        )
    )


def _settings(tmp_path, directory: str) -> Settings:
    return Settings(
        storage_root=str(tmp_path / directory),
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )


def test_fresh_bootstrap_generates_one_stable_server_identity(tmp_path) -> None:
    settings = _settings(tmp_path, "fresh-storage")
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            first_identity = _read_server_identity(db)

        bootstrap_database(engine, settings)
        with Session(engine) as db:
            repeated_identity = _read_server_identity(db)

        assert first_identity is not None
        assert re.fullmatch(r"server_[0-9a-f]{32}", first_identity)
        assert repeated_identity == first_identity
    finally:
        engine.dispose()


def test_existing_database_bootstrap_adds_identity_without_replacing_settings(
    tmp_path,
) -> None:
    settings = _settings(tmp_path, "existing-storage")
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        apply_schema(engine, settings)
        with Session(engine) as db, db.begin():
            db.add(SystemSetting(key="systemName", value="Existing library"))

        bootstrap_database(engine, settings)

        with Session(engine) as db:
            assert db.get(SystemSetting, "systemName").value == "Existing library"
            assert _read_server_identity(db) is not None
    finally:
        engine.dispose()


def test_backup_restore_preserves_server_identity(tmp_path) -> None:
    settings = _settings(tmp_path, "backup-storage")
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            original_identity = _read_server_identity(db)
            backup = create_backup(db, settings)

        with Session(engine) as db, db.begin():
            identity_setting = db.get(SystemSetting, SERVER_IDENTITY_SETTING_KEY)
            assert identity_setting is not None
            identity_setting.value = "server_replaced_after_backup"

        with Session(engine) as db:
            restore_backup(db, settings, backup.id)

        with Session(engine) as db:
            assert _read_server_identity(db) == original_identity
    finally:
        engine.dispose()
