from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, insert, inspect, select

from app.core.config import Settings
from app.db.base import Base
from app.db.runner import _run_alembic, apply_schema, head_revision
from app.db.sqlite import create_sqlite_engine


def _table(engine, name: str) -> Table:
    return Table(name, MetaData(), autoload_with=engine)


def test_0003_upgrade_merges_same_media_editions_without_losing_volumes(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    now = datetime.now(UTC)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0003_import_work_queue"),
        )
        work = _table(engine, "LibraryWork")
        edition = _table(engine, "LibraryEdition")
        volume = _table(engine, "LibraryVolume")
        file = _table(engine, "LibraryFile")
        reading_unit = _table(engine, "LibraryReadingUnit")
        import_task = _table(engine, "ImportTask")
        import_asset = _table(engine, "ImportAsset")
        import_log = _table(engine, "ImportLog")
        import_work_item = _table(engine, "ImportWorkItem")
        conversion = _table(engine, "BookConversionTask")
        user = _table(engine, "User")
        progress = _table(engine, "LibraryReadingProgress")
        with engine.begin() as connection:
            connection.execute(
                insert(user).values(
                    id="user-1",
                    email="reader@example.test",
                    name="Reader",
                    passwordHash="not-a-real-hash",
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(work).values(
                    id="work-1",
                    title="示例",
                    normalizedTitle="示例",
                    workType="EPUB",
                    status="READING",
                    tags="[]",
                    primaryEditionId="edition-a",
                    updatedAt=now,
                )
            )
            for edition_id, format_name, primary in (
                ("edition-a", "EPUB", True),
                ("edition-b", "PDF", False),
            ):
                connection.execute(
                    insert(edition).values(
                        id=edition_id,
                        workId="work-1",
                        origin="UPLOAD",
                        mediaKind="EBOOK",
                        format=format_name,
                        versionName=format_name,
                        versionKey=f"legacy:{edition_id}",
                        importStatus="READY",
                        sizeBytes=10,
                        coverStatus="PENDING",
                        primary=primary,
                        hidden=False,
                        updatedAt=now,
                    )
                )
                volume_id = f"volume-{edition_id[-1]}"
                connection.execute(
                    insert(volume).values(
                        id=volume_id,
                        editionId=edition_id,
                        title="第 1 卷",
                        volumeIndex=1,
                        sortOrder=0,
                        updatedAt=now,
                    )
                )
                connection.execute(
                    insert(file).values(
                        id=f"file-{edition_id[-1]}",
                        editionId=edition_id,
                        volumeId=volume_id,
                        path=f"/library/{edition_id}.{format_name.lower()}",
                        hashStatus="READY",
                        mtimeMs=1,
                        kind="BOOK",
                        mimeType="application/octet-stream",
                        sizeBytes=10,
                        sortOrder=0,
                        updatedAt=now,
                    )
                )
                if edition_id == "edition-a":
                    connection.execute(
                        insert(reading_unit).values(
                            id="unit-a",
                            editionId=edition_id,
                            volumeId=None,
                            fileId="file-a",
                            unitType="CHAPTER",
                            title="Chapter 1",
                            href="chapter.xhtml",
                            sortOrder=0,
                            metadataJson="{}",
                            updatedAt=now,
                        )
                    )
            for progress_id, percent, updated_at in (
                ("progress-old", 25, now),
                ("progress-new", 75, now + timedelta(seconds=1)),
            ):
                connection.execute(
                    insert(progress).values(
                        id=progress_id,
                        userId="user-1",
                        workId="work-1",
                        editionId="edition-a",
                        volumeId=None,
                        readerType="EPUB",
                        position='{"href":"chapter.xhtml"}',
                        percent=percent,
                        extra="{}",
                        updatedAt=updated_at,
                    )
                )
            connection.execute(
                insert(import_task).values(
                    id="import-1",
                    workId="work-1",
                    editionId="edition-a",
                    volumeId="volume-a",
                    origin="UPLOAD",
                    status="COMPLETED",
                    sourcePath="/incoming/book.epub",
                    taskKind="FILE",
                    assetCount=1,
                    processedAssetCount=1,
                    progress=100,
                    duplicate=False,
                    duration=1,
                    retryable=False,
                    attempts=1,
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(import_asset).values(
                    id="asset-1",
                    importTaskId="import-1",
                    sourcePath="/incoming/book.epub",
                    status="COMPLETED",
                    sortOrder=0,
                    fileId="file-a",
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(import_log).values(
                    id="log-1",
                    importTaskId="import-1",
                    level="info",
                    message="imported",
                )
            )
            connection.execute(
                insert(import_work_item).values(
                    id="work-item-1",
                    kind="IMPORT_SOURCE",
                    importTaskId="import-1",
                    dedupeKey="import:1",
                    status="COMPLETED",
                    priority=100,
                    availableAt=now,
                    attempts=1,
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(conversion).values(
                    id="conversion-1",
                    importTaskId="import-1",
                    mode="AUTO",
                    sourceFormat="MOBI",
                    targetFormat="EPUB",
                    sourcePath="/incoming/book.mobi",
                    converter="shuku-internal",
                    optionsJson="{}",
                    status="COMPLETED",
                    progress=100,
                    attempts=1,
                    retryable=False,
                    updatedAt=now,
                )
            )

        apply_schema(engine, settings)

        assert head_revision(engine) == "0011_reader_progress_sources"
        upgraded_volume = _table(engine, "LibraryVolume")
        upgraded_task = _table(engine, "ImportTask")
        upgraded_folder = _table(engine, "MonitorFolder")
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(upgraded_volume.c.classificationSource).limit(1)
                )
                == "LEGACY"
            )
            assert (
                connection.scalar(
                    select(upgraded_volume.c.classificationReason).limit(1)
                )
                == "LEGACY"
            )
            assert "mediaKindPolicy" in upgraded_task.c
            assert "mediaKindPolicy" in upgraded_folder.c
        inspector = inspect(engine)
        assert "LibraryEdition" not in inspector.get_table_names()
        assert "LibraryEditionFacet" not in inspector.get_table_names()
        assert {column["name"] for column in inspector.get_columns("LibraryFile")} >= {
            "volumeId"
        }
        assert "editionId" not in {
            column["name"] for column in inspector.get_columns("LibraryFile")
        }

        media_version = _table(engine, "LibraryMediaVersion")
        migrated_volume = _table(engine, "LibraryVolume")
        with engine.connect() as connection:
            assert connection.execute(select(media_version.c.id)).scalars().all() == [
                "edition-a"
            ]
            rows = connection.execute(
                select(
                    migrated_volume.c.id,
                    migrated_volume.c.mediaVersionId,
                    migrated_volume.c.volumeIndex,
                    migrated_volume.c.sortOrder,
                ).order_by(migrated_volume.c.sortOrder)
            ).all()
            assert rows == [
                ("volume-a", "edition-a", 1.0, 0),
                ("volume-b", "edition-a", 1.0, 1),
            ]
            assert (
                connection.scalar(select(_table(engine, "ImportTask").c.id))
                == "import-1"
            )
            assert (
                connection.scalar(select(_table(engine, "ImportAsset").c.id))
                == "asset-1"
            )
            assert (
                connection.scalar(select(_table(engine, "ImportLog").c.id)) == "log-1"
            )
            assert (
                connection.scalar(select(_table(engine, "ImportWorkItem").c.id))
                == "work-item-1"
            )
            assert (
                connection.scalar(select(_table(engine, "BookConversionTask").c.id))
                == "conversion-1"
            )
            migrated_unit = _table(engine, "LibraryReadingUnit")
            assert connection.execute(
                select(migrated_unit.c.volumeId, migrated_unit.c.fileId).where(
                    migrated_unit.c.id == "unit-a"
                )
            ).one() == ("volume-a", "file-a")
            migrated_progress = _table(engine, "LibraryReadingProgress")
            progress_rows = connection.execute(
                select(
                    migrated_progress.c.id,
                    migrated_progress.c.volumeId,
                    migrated_progress.c.percent,
                )
            ).all()
            assert progress_rows == [("progress-new", "volume-a", 75.0)]
            progression_source = connection.execute(
                select(
                    migrated_progress.c.progressedAt,
                    migrated_progress.c.sourceProtocol,
                    migrated_progress.c.sourceDeviceName,
                ).where(migrated_progress.c.id == "progress-new")
            ).one()
            assert progression_source.progressedAt is not None
            assert progression_source.sourceProtocol == "SHUKU_WEB"
            assert progression_source.sourceDeviceName == "Shuku Web Reader"
            migration_event = _table(engine, "MediaVersionMigrationEvent")
            assert (
                connection.scalar(
                    select(migration_event.c.code).where(
                        migration_event.c.recordId == "progress-old"
                    )
                )
                == "DUPLICATE_PROGRESS_COLLAPSED"
            )
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
        assert list(
            settings.database_path.parent.glob(
                "migrations/shuku-before-alembic-*.sqlite3"
            )
        )
    finally:
        engine.dispose()


def test_contract_discards_conversion_without_source_volume_and_completes_upgrade(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage-invalid-conversion"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    now = datetime.now(UTC)
    try:
        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0003_import_work_queue"),
        )
        import_task = _table(engine, "ImportTask")
        conversion = _table(engine, "BookConversionTask")
        with engine.begin() as connection:
            connection.execute(
                insert(import_task).values(
                    id="orphaned-import",
                    origin="UPLOAD",
                    status="FAILED",
                    sourcePath="/incoming/broken.mobi",
                    taskKind="FILE",
                    assetCount=1,
                    processedAssetCount=0,
                    progress=0,
                    duplicate=False,
                    duration=0,
                    retryable=False,
                    attempts=1,
                    updatedAt=now,
                )
            )
            connection.execute(
                insert(conversion).values(
                    id="orphaned-conversion",
                    importTaskId="orphaned-import",
                    mode="AUTO",
                    sourceFormat="MOBI",
                    targetFormat="EPUB",
                    sourcePath="/incoming/broken.mobi",
                    converter="shuku-internal",
                    optionsJson="{}",
                    status="FAILED",
                    progress=0,
                    attempts=1,
                    retryable=False,
                    updatedAt=now,
                )
            )

        _run_alembic(
            engine,
            lambda config: command.upgrade(config, "0006_media_versions_backfill"),
        )
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == "0006_media_versions_backfill"
            )

        apply_schema(engine, settings)

        with engine.connect() as connection:
            assert (
                connection.scalar(select(_table(engine, "BookConversionTask").c.id))
                is None
            )
            assert connection.scalar(select(_table(engine, "ImportTask").c.id)) == (
                "orphaned-import"
            )
            assert head_revision(engine) == "0011_reader_progress_sources"
            assert "LibraryEdition" not in inspect(connection).get_table_names()

        apply_schema(engine, settings)
        assert head_revision(engine) == "0011_reader_progress_sources"
    finally:
        engine.dispose()
