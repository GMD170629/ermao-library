from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.modules.media.infrastructure.comic_page_index_migration as persistence
from app.bootstrap.comic_page_index_migration import (
    ComicPageIndexDataMigrationError,
    comic_page_index_data_migration_is_complete,
    run_comic_page_index_data_migration,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from tests.support.sqlalchemy import StatementRecorder


def _write_comic_archive(path: Path, page_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for page_index in range(1, page_count + 1):
            archive.writestr(f"{page_index:03}.jpg", f"page-{page_index}".encode())


def _seed_pending_comics(
    engine: Engine,
    settings: Settings,
    *,
    volume_count: int,
    page_count: int,
) -> dict[str, datetime]:
    preserved: dict[str, datetime] = {}
    works: list[LibraryWork] = []
    media_versions: list[LibraryMediaVersion] = []
    volumes: list[LibraryVolume] = []
    files: list[LibraryFile] = []
    with Session(engine) as db:
        for index in range(volume_count):
            archive_path = (
                settings.resolved_storage_root / "library" / f"comic-{index:03}.cbz"
            )
            _write_comic_archive(archive_path, page_count)
            updated_at = datetime(2026, 8, 11, 8, index % 60, tzinfo=UTC)
            work = LibraryWork(
            library_id="test-library", 
                id=f"comic-work-{index:03}",
                origin="MANUAL",
                title=f"Comic {index}",
                normalized_title=f"comic {index}",
                author="作者",
                normalized_author="作者",
                tags="[]",
            )
            media = LibraryMediaVersion(
                id=f"comic-media-{index:03}",
                work_id=work.id,
                media_kind="COMIC",
            )
            volume = LibraryVolume(
                id=f"comic-volume-{index:03}",
                media_version_id=media.id,
                title=f"第 {index + 1} 卷",
                format="CBZ",
                resource_key=f"migration:comic:{index}",
                import_status="COMPLETED",
                page_count=page_count,
                updated_at=updated_at,
            )
            file = LibraryFile(
                id=f"comic-file-{index:03}",
                volume_id=volume.id,
                path=str(archive_path),
                file_path_hash=f"comic-path-{index:03}",
                mtime_ms=int(archive_path.stat().st_mtime * 1000),
                kind="COMIC",
                mime_type="application/zip",
                size_bytes=archive_path.stat().st_size,
                page_index_version=0,
                updated_at=updated_at,
            )
            works.append(work)
            media_versions.append(media)
            volumes.append(volume)
            files.append(file)
            preserved[volume.id] = updated_at
            preserved[file.id] = updated_at
        db.add_all(works)
        db.flush()
        db.add_all(media_versions)
        db.flush()
        db.add_all(volumes)
        db.flush()
        db.add_all(files)
        db.commit()
    return preserved


def _runtime(tmp_path: Path) -> tuple[Settings, Engine, sessionmaker[Session]]:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return settings, engine, sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def test_startup_data_migration_batches_25_comics_with_bounded_dml(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, engine, factory = _runtime(tmp_path)
    try:
        preserved = _seed_pending_comics(
            engine,
            settings,
            volume_count=25,
            page_count=5,
        )
        assert comic_page_index_data_migration_is_complete(factory) is False
        with caplog.at_level(logging.INFO), StatementRecorder(engine) as recorder:
            recorder.reset_after_warmup()
            run_comic_page_index_data_migration(factory, settings)

        assert recorder.dml_count <= 6
        assert comic_page_index_data_migration_is_complete(factory) is True
        messages = [record.getMessage() for record in caplog.records]
        assert any("outcome=started" in message for message in messages)
        assert any("outcome=progress" in message for message in messages)
        assert any("outcome=success" in message for message in messages)
        with Session(engine) as verification:
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 125
            assert set(
                verification.scalars(select(LibraryFile.page_index_version))
            ) == {1}
            first_page = verification.scalars(
                select(LibraryReadingUnit).order_by(LibraryReadingUnit.sort_order)
            ).first()
            assert first_page is not None
            metadata = json.loads(first_page.metadata_json)
            assert metadata["originalName"] == "001.jpg"
            assert metadata["pageInVolume"] == 1
            assert metadata["pageInSection"] == 1
            volume_times = dict(
                verification.execute(
                    select(LibraryVolume.id, LibraryVolume.updated_at)
                ).all()
            )
            file_times = dict(
                verification.execute(
                    select(LibraryFile.id, LibraryFile.updated_at)
                ).all()
            )
        assert all(
            preserved[record_id] == value
            for record_id, value in volume_times.items()
        )
        assert all(
            preserved[record_id] == value
            for record_id, value in file_times.items()
        )

        with StatementRecorder(engine) as rerun_recorder:
            rerun_recorder.reset_after_warmup()
            run_comic_page_index_data_migration(factory, settings)
        assert rerun_recorder.dml_count == 0
    finally:
        engine.dispose()


def test_startup_data_migration_avoids_reparse_and_uses_dense_page_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, engine, factory = _runtime(tmp_path)
    parse_calls = 0
    inspect_archive = persistence.inspect_comic_archive

    def count_archive_inspection(
        path: Path,
        original_name: str | None = None,
    ) -> object:
        nonlocal parse_calls
        parse_calls += 1
        return inspect_archive(path, original_name)

    monkeypatch.setattr(
        persistence,
        "inspect_comic_archive",
        count_archive_inspection,
    )
    try:
        _seed_pending_comics(
            engine,
            settings,
            volume_count=5,
            page_count=180,
        )
        with StatementRecorder(engine) as recorder:
            recorder.reset_after_warmup()
            run_comic_page_index_data_migration(factory, settings)

        assert parse_calls == 5
        assert recorder.dml_count <= 15
        with Session(engine) as verification:
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 900
            assert set(
                verification.scalars(select(LibraryFile.page_index_version))
            ) == {1}
    finally:
        engine.dispose()


def test_startup_data_migration_failure_leaves_api_prerequisite_pending(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, engine, factory = _runtime(tmp_path)
    try:
        _seed_pending_comics(engine, settings, volume_count=1, page_count=2)
        archive_path = settings.resolved_storage_root / "library" / "comic-000.cbz"
        archive_path.unlink()

        with caplog.at_level(logging.INFO), pytest.raises(
            ComicPageIndexDataMigrationError
        ):
            run_comic_page_index_data_migration(factory, settings)

        with Session(engine) as verification:
            assert verification.scalar(select(LibraryFile.page_index_version)) == 0
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 0
        messages = [record.getMessage() for record in caplog.records]
        assert any("outcome=started" in message for message in messages)
        assert any("outcome=failed" in message for message in messages)
        assert not any("outcome=success" in message for message in messages)
    finally:
        engine.dispose()


def test_startup_data_migration_reuses_complete_rows_without_reading_archive(
    tmp_path: Path,
) -> None:
    settings, engine, factory = _runtime(tmp_path)
    try:
        _seed_pending_comics(engine, settings, volume_count=1, page_count=2)
        with Session(engine) as db:
            db.add_all(
                [
                    LibraryReadingUnit(
                        id=f"existing-comic-page-{page_index}",
                        volume_id="comic-volume-000",
                        file_id="comic-file-000",
                        unit_type="page",
                        title=f"第 {page_index} 页",
                        href=f"{page_index:03}.jpg",
                        media_type="image/jpeg",
                        sort_order=page_index,
                        size=6,
                        metadata_json="{}",
                    )
                    for page_index in range(1, 3)
                ]
            )
            db.commit()
        archive_path = settings.resolved_storage_root / "library" / "comic-000.cbz"
        archive_path.unlink()

        run_comic_page_index_data_migration(factory, settings)

        with Session(engine) as verification:
            assert verification.scalar(select(LibraryFile.page_index_version)) == 1
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 2
    finally:
        engine.dispose()


def test_startup_data_migration_resumes_completed_batches_after_failure(
    tmp_path: Path,
) -> None:
    settings, engine, factory = _runtime(tmp_path)
    try:
        _seed_pending_comics(engine, settings, volume_count=2, page_count=2)
        failed_archive = (
            settings.resolved_storage_root / "library" / "comic-001.cbz"
        )
        failed_archive.unlink()

        with pytest.raises(ComicPageIndexDataMigrationError):
            run_comic_page_index_data_migration(factory, settings)

        with Session(engine) as verification:
            versions = dict(
                verification.execute(
                    select(LibraryFile.id, LibraryFile.page_index_version)
                ).all()
            )
            assert versions == {"comic-file-000": 1, "comic-file-001": 0}
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 2

        _write_comic_archive(failed_archive, 2)
        run_comic_page_index_data_migration(factory, settings)

        with Session(engine) as verification:
            assert set(
                verification.scalars(select(LibraryFile.page_index_version))
            ) == {1}
            assert verification.scalar(
                select(func.count()).select_from(LibraryReadingUnit)
            ) == 4
    finally:
        engine.dispose()
