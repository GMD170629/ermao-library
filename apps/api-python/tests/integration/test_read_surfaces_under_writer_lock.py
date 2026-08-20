from __future__ import annotations

from pathlib import Path
from time import monotonic

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.maintenance import (
    DATABASE_MAINTENANCE_RESTORE_VALUE,
    DATABASE_MAINTENANCE_SETTING_KEY,
)
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import SystemSetting
from tests.support.sqlalchemy import StatementRecorder


def _seed_read_surfaces(engine: Engine) -> None:
    with Session(engine) as db:
        db.add(
            User(
                id="writer-lock-admin",
                email="writer-lock@example.com",
                name="Writer lock admin",
                password_hash=hash_password("starshipnas"),
                role="admin",
            )
        )
        work = LibraryWork(
            library_id="test-library", 
            id="writer-lock-work",
            origin="MANUAL",
            title="Writer lock reader",
            normalized_title="writer lock reader",
            author="作者",
            normalized_author="作者",
            tags="[]",
        )
        media = LibraryMediaVersion(
            id="writer-lock-media",
            work_id=work.id,
            media_kind="EBOOK",
        )
        volume = LibraryVolume(
            id="writer-lock-volume",
            version_id=media.id,
            title="电子书",
            format="EPUB",
            resource_key="manual:writer-lock",
            import_status="COMPLETED",
        )
        file = LibraryFile(
            id="writer-lock-file",
            volume_id=volume.id,
            path="library/writer-lock.epub",
            fingerprint=f"sha256:{'a' * 64}",
            full_hash="a" * 64,
            hash_status="COMPLETED",
            mtime_ms=1,
            kind="EPUB",
            mime_type="application/epub+zip",
            size_bytes=10,
        )
        db.add(work)
        db.commit()
        db.add(media)
        db.commit()
        db.add(volume)
        db.commit()
        db.add(file)
        db.commit()


def test_get_surfaces_remain_read_only_while_writer_slot_is_held(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    regular_engine = create_sqlite_engine(settings.database_path)
    reader_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.1)
    bootstrap_database(regular_engine, settings)
    _seed_read_surfaces(regular_engine)
    reader_factory = sessionmaker(
        bind=reader_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=reader_factory)
    blocker = Session(regular_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "writer-lock@example.com",
                    "password": "starshipnas",
                },
            )
            assert login.status_code == 200
            blocker.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "systemName")
                .values(value="writer owns SQLite slot")
            )

            with StatementRecorder(reader_engine) as recorder:
                recorder.reset_after_warmup()
                for path in (
                    "/api/auth/me",
                    "/api/sources",
                    "/api/library/facets",
                    "/api/reader/v4/volumes/writer-lock-volume/bootstrap",
                ):
                    started_at = monotonic()
                    response = client.get(path)
                    elapsed = monotonic() - started_at
                    assert response.status_code == 200, (path, response.text)
                    assert elapsed < 0.75, (path, elapsed)

                assert recorder.dml_count == 0
    finally:
        blocker.rollback()
        blocker.close()
        reader_engine.dispose()
        regular_engine.dispose()


def test_maintenance_state_rejects_new_writes_but_keeps_gets_available(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    _seed_read_surfaces(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "email": "writer-lock@example.com",
                "password": "starshipnas",
            },
        )
        assert login.status_code == 200
        with Session(engine) as maintenance:
            maintenance.add(
                SystemSetting(
                    key=DATABASE_MAINTENANCE_SETTING_KEY,
                    value=DATABASE_MAINTENANCE_RESTORE_VALUE,
                )
            )
            maintenance.commit()

        assert client.get("/api/auth/me").status_code == 200
        response = client.post("/api/auth/session/refresh")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_MAINTENANCE"
    engine.dispose()
