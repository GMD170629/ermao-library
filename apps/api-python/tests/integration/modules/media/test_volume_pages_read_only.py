from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import SystemSetting
from tests.support.sqlalchemy import StatementRecorder


def _write_comic_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("001.jpg", b"one")
        archive.writestr("002.jpg", b"two")


def _seed_comic(engine: Engine, settings: Settings) -> datetime:
    archive_path = settings.resolved_storage_root / "library" / "comic.cbz"
    _write_comic_archive(archive_path)
    preserved_updated_at = datetime(2026, 8, 11, 8, tzinfo=UTC)
    with Session(engine) as db:
        user = User(
            id="comic-lock-admin",
            email="comic-lock@example.com",
            name="Comic lock admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
        work = LibraryWork(
            library_id="test-library", 
            id="comic-lock-work",
            origin="MANUAL",
            title="Comic lock",
            normalized_title="comic lock",
            author="作者",
            normalized_author="作者",
            tags="[]",
        )
        media = LibraryMediaVersion(
            id="comic-lock-media",
            work_id=work.id,
            media_kind="COMIC",
        )
        volume = LibraryVolume(
            id="comic-lock-volume",
            version_id=media.id,
            title="第一卷",
            format="CBZ",
            resource_key="manual:comic-lock",
            import_status="COMPLETED",
            page_count=None,
            updated_at=preserved_updated_at,
        )
        file = LibraryFile(
            id="comic-lock-file",
            volume_id=volume.id,
            path=str(archive_path.resolve()),
            fingerprint="sha256:comic-lock",
            hash_status="COMPLETED",
            mtime_ms=1,
            kind="COMIC",
            mime_type="application/zip",
            size_bytes=archive_path.stat().st_size,
        )
        db.add_all([user, work])
        db.flush()
        db.add(media)
        db.flush()
        db.add(volume)
        db.flush()
        db.add(file)
        db.commit()
    return preserved_updated_at


def test_missing_comic_page_index_does_not_fallback_while_writer_is_held(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    writer_engine = create_sqlite_engine(settings.database_path)
    reader_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.1)
    bootstrap_database(writer_engine, settings)
    preserved_updated_at = _seed_comic(writer_engine, settings)
    reader_factory = sessionmaker(
        bind=reader_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=reader_factory)
    blocker = Session(writer_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "comic-lock@example.com",
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
                started_at = monotonic()
                listed = client.get("/api/volumes/comic-lock-volume/pages")
                list_elapsed = monotonic() - started_at
                started_at = monotonic()
                page = client.get("/api/volumes/comic-lock-volume/pages/2")
                page_elapsed = monotonic() - started_at

            assert listed.status_code == 200
            assert listed.json()["data"]["pages"] == []
            assert page.status_code == 404
            assert list_elapsed < 0.75
            assert page_elapsed < 0.75
            assert recorder.dml_count == 0

            with Session(reader_engine) as verification:
                page_rows = verification.scalar(
                    select(func.count()).select_from(LibraryReadingUnit)
                )
                volume_state = verification.execute(
                    select(LibraryVolume.page_count, LibraryVolume.updated_at).where(
                        LibraryVolume.id == "comic-lock-volume"
                    )
                ).one()
            assert page_rows == 0
            assert volume_state == (None, preserved_updated_at)
    finally:
        blocker.rollback()
        blocker.close()
        reader_engine.dispose()
        writer_engine.dispose()
