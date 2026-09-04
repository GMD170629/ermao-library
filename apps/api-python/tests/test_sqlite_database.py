from __future__ import annotations

import hashlib
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db import runner as runner_module
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.runner import head_revision
from app.db.seed import seed_baseline_data
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
    LibrarySourceNodeMetadata,
)
from app.models.import_pipeline import Source
from app.models.settings import ReaderBookPreference, SystemSetting
from app.modules.backup.infrastructure.archive import (
    backup_path,
    create_backup,
    restore_backup,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY

TARGET_CORE_TABLES = frozenset(
    {
        "LibrarySourceNode",
        "LibrarySourceNodeMetadata",
        "LibrarySourceNodeInterpretation",
        "LibraryBook",
        "LibraryBookMetadata",
        "LibraryReadableResource",
        "LibraryReadableResourceMetadata",
        "LibraryResourceAsset",
        "LibraryResourceAssetMetadata",
        "LibraryImportTask",
    }
)

LEGACY_TABLES = frozenset(
    {
        "LibraryImportRun",
        "ResourceCandidate",
        "AssetCandidate",
        "LibraryWork",
        "LibraryVersion",
        "LibraryVolume",
        "LibraryFile",
        "LibraryMediaVersion",
        "LibraryReadingUnit",
        "LibraryReadingProgress",
        "LibraryMetadata",
        "LibraryWorkFacet",
        "LibraryVolumeFacet",
        "ShelfWork",
        "WorkDetailPreference",
        "ImportTask",
        "ImportScanJob",
        "ImportWorkItem",
        "ImportAsset",
        "ImportLog",
        "BookIdentityCache",
        "QueueControlOperation",
        "MonitorFolder",
        "UserMonitorFolderAccess",
        "DuplicateCandidate",
        "MediaVersionMigrationEvent",
        "UserMediaHistory",
    }
)


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _application_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _sqlite_journal_mode(engine) -> str:
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        try:
            row = cursor.execute("PRAGMA journal_mode").fetchone()
        finally:
            cursor.close()
    finally:
        raw_connection.close()
    assert row is not None
    return str(row[0]).lower()


def _assert_all_foreign_keys_have_lookup_indexes(engine) -> None:
    inspector = inspect(engine)
    for table_name in Base.metadata.tables:
        indexed_columns: list[tuple[tuple[str, ...], bool]] = []
        primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns")
        if primary_key:
            indexed_columns.append((tuple(primary_key), True))
        for constraint in inspector.get_unique_constraints(table_name):
            columns = constraint.get("column_names")
            if columns:
                indexed_columns.append((tuple(columns), True))
        for index in inspector.get_indexes(table_name):
            sqlite_where = index.get("dialect_options", {}).get("sqlite_where")
            columns = index.get("column_names")
            if sqlite_where is None and columns:
                indexed_columns.append((tuple(columns), bool(index.get("unique"))))
        for foreign_key in inspector.get_foreign_keys(table_name):
            columns = foreign_key.get("constrained_columns")
            assert columns
            foreign_key_columns = tuple(columns)
            assert any(
                indexed[: len(foreign_key_columns)] == foreign_key_columns
                or (
                    unique
                    and len(indexed) <= len(foreign_key_columns)
                    and foreign_key_columns[: len(indexed)] == indexed
                )
                for indexed, unique in indexed_columns
            ), (
                table_name,
                foreign_key,
            )


def test_sqlite_engine_enables_persistent_wal_mode(tmp_path) -> None:
    database_path = tmp_path / "wal-mode.sqlite3"
    metadata = MetaData()
    probe = Table(
        "WalModeProbe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("value", String(32), nullable=False),
    )
    default_engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        metadata.create_all(default_engine)
        with default_engine.begin() as connection:
            connection.execute(probe.insert().values(id=1, value="preserved"))
        assert _sqlite_journal_mode(default_engine) == "delete"
    finally:
        default_engine.dispose()

    engine = create_sqlite_engine(database_path)
    try:
        assert _sqlite_journal_mode(engine) == "wal"
        with engine.connect() as connection:
            assert connection.scalar(select(probe.c.value)) == "preserved"
    finally:
        engine.dispose()

    independent_engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        assert _sqlite_journal_mode(independent_engine) == "wal"
    finally:
        independent_engine.dispose()


def test_empty_storage_bootstraps_current_directory_topology_schema(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        bootstrap_database(engine, settings)

        assert settings.database_path.is_file()
        assert _application_tables(engine) == set(Base.metadata.tables)
        assert _current_revision(engine) == head_revision(engine)

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert TARGET_CORE_TABLES <= table_names
        assert {
            "Library",
            "LibrarySourceNode",
            "LibraryBook",
            "LibraryReadableResource",
            "LibraryResourceAsset",
            "LibraryImportTask",
            "LibraryBookFacet",
            "LibraryReadableResourceFacet",
            "ShelfBook",
            "BookDetailPreference",
            "ReaderBookPreference",
            "ReaderProgressCursor",
            "ReaderResourceProgress",
            "ReaderProgressMutation",
            "ReaderBookmark",
            "ReaderResourceProgressV5",
            "ReaderProgressMutationV5",
            "ReaderResourceReadingStatusV5",
            "ReaderBookmarkV5",
            "ReadableResourceNavigationUnit",
            "LibraryResourceAssetNavigation",
        } <= table_names
        assert LEGACY_TABLES.isdisjoint(table_names)

        library_columns = {
            column["name"]: column for column in inspector.get_columns("Library")
        }
        assert library_columns["rootPath"]["nullable"] is False
        assert library_columns["organizationMode"]["nullable"] is False
        library_unique_columns = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("Library")
        } | {
            tuple(index["column_names"])
            for index in inspector.get_indexes("Library")
            if index.get("unique")
        }
        assert ("rootPath",) in library_unique_columns
        library_checks = " ".join(
            str(constraint["sqltext"])
            for constraint in inspector.get_check_constraints("Library")
        )
        assert "'FLAT'" in library_checks
        assert "'VOLUMES'" in library_checks
        assert "AUDIOBOOK" not in library_checks

        book_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryBook")
        }
        resource_columns = {
            column["name"]: column
            for column in inspector.get_columns("LibraryReadableResource")
        }
        asset_columns = {
            column["name"]: column
            for column in inspector.get_columns("LibraryResourceAsset")
        }
        assert book_columns["libraryId"]["nullable"] is False
        assert book_columns["sourceNodeId"]["nullable"] is False
        assert resource_columns["bookId"]["nullable"] is False
        assert resource_columns["sourceNodeId"]["nullable"] is False
        assert asset_columns["resourceId"]["nullable"] is False
        assert asset_columns["sourceNodeId"]["nullable"] is False

        source_node_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("LibrarySourceNode")
        }
        assert "LibrarySourceNode_pathKey_format_check" in source_node_checks
        source_node_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("LibrarySourceNode")
        }
        assert source_node_indexes["LibrarySourceNode_parentId_idx"] == ("parentId",)
        import_task_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes("LibraryImportTask")
        }
        assert "LibraryImportTask_import_asset_key" in import_task_indexes
        assert "LibraryImportTask_queued_createdAt_idx" in import_task_indexes
        assert import_task_indexes["LibraryImportTask_sourceNodeId_idx"] == (
            "sourceNodeId",
        )

        import_task_columns = {
            column["name"] for column in inspector.get_columns("LibraryImportTask")
        }
        assert import_task_columns == {
            "id",
            "kind",
            "libraryId",
            "resourceId",
            "sourceNodeId",
            "role",
            "state",
            "errorSummary",
            "missingEntryPolicy",
            "createdAt",
            "startedAt",
            "finishedAt",
        }
        assert {
            "attempts",
            "priority",
            "availableAt",
            "leaseOwnerId",
            "leaseExpiresAt",
            "heartbeatAt",
            "claimVersion",
            "fencingToken",
        }.isdisjoint(import_task_columns)
        for table_name in Base.metadata.tables:
            for foreign_key in inspector.get_foreign_keys(table_name):
                assert foreign_key["options"].get("onupdate") == "CASCADE", (
                    table_name,
                    foreign_key,
                )
        _assert_all_foreign_keys_have_lookup_indexes(engine)

        for table_name in Base.metadata.tables:
            created_at = next(
                (
                    column
                    for column in inspector.get_columns(table_name)
                    if column["name"] == "createdAt"
                ),
                None,
            )
            if created_at is not None:
                assert "unixepoch()" in str(created_at["default"]), table_name

        with Session(engine) as db:
            assert db.scalar(select(SystemSetting).where(False)) is None
            settings_by_key = {
                row.key: row.value for row in db.scalars(select(SystemSetting)).all()
            }
            server_identity = settings_by_key.pop(SERVER_IDENTITY_SETTING_KEY)
            assert re.fullmatch(r"server_[0-9a-f]{32}", server_identity)
            assert settings_by_key == {
                "language": "zh-CN",
                "systemName": "二毛图书",
            }
            sources = db.scalars(
                select(Source)
                .where(Source.kind == "metadata")
                .order_by(Source.provider_type)
            ).all()
            assert [(source.provider_type, source.enabled) for source in sources] == [
                ("ai", False),
                ("bangumi", True),
                ("douban", True),
            ]

        assert ReaderBookPreference.__table__.c.schemaVersion.default.arg == 3
        assert (
            str(ReaderBookPreference.__table__.c.schemaVersion.server_default.arg)
            == "3"
        )
    finally:
        engine.dispose()


def test_alembic_script_directory_has_one_linear_head() -> None:
    from alembic.script import ScriptDirectory

    from app.db.runner import alembic_config_for_engine, head_revision

    config = alembic_config_for_engine(create_engine("sqlite+pysqlite:///:memory:"))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    assert len(revisions) == 9
    assert script.get_heads() == ["0009_reader_v5_opaque_progress"]
    assert head_revision() == "0009_reader_v5_opaque_progress"
    assert [revision.revision for revision in revisions] == [
        "0009_reader_v5_opaque_progress",
        "0008_foreign_key_lookup_indexes",
        "0007_source_node_lookup_indexes",
        "0006_import_task_missing_entry_policy",
        "0005_asset_navigation_marker",
        "0004_remove_media_kind",
        "0003_audio_asset_title",
        "0002_library_scan_queue_uniqueness",
        "0001_library_topology_baseline",
    ]
    assert revisions[0].down_revision == "0008_foreign_key_lookup_indexes"
    assert revisions[1].down_revision == "0007_source_node_lookup_indexes"
    assert revisions[2].down_revision == "0006_import_task_missing_entry_policy"
    assert revisions[3].down_revision == "0005_asset_navigation_marker"
    assert revisions[4].down_revision == "0004_remove_media_kind"
    assert revisions[5].down_revision == "0003_audio_asset_title"
    assert revisions[6].down_revision == "0002_library_scan_queue_uniqueness"
    assert revisions[7].down_revision == "0001_library_topology_baseline"
    assert revisions[8].down_revision is None


def test_fresh_baseline_contains_source_node_writeback_schema(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        runner_module.apply_schema(engine, settings)
        assert _current_revision(engine) == "0009_reader_v5_opaque_progress"
        operation_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("MetadataWritebackOperation")
        }
        assert operation_columns["sourceNodeId"]["nullable"] is False
        assert operation_columns["resourceId"]["nullable"] is True
        preparation_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("MetadataWritebackPreparation")
        }
        assert preparation_columns["sourceNodeId"]["nullable"] is False
        asset_metadata_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("LibraryResourceAssetMetadata")
        }
        assert asset_metadata_columns["title"]["nullable"] is True
    finally:
        engine.dispose()


def test_source_node_lookup_indexes_upgrade_from_previous_head(tmp_path) -> None:
    from alembic import command

    from app.db.runner import alembic_config_for_engine

    engine = create_sqlite_engine(tmp_path / "source-node-index-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0006_import_task_missing_entry_policy")

        assert "LibrarySourceNode_parentId_idx" not in {
            index["name"] for index in inspect(engine).get_indexes("LibrarySourceNode")
        }
        assert "LibraryImportTask_sourceNodeId_idx" not in {
            index["name"] for index in inspect(engine).get_indexes("LibraryImportTask")
        }

        runner_module.apply_schema(engine)
        assert _current_revision(engine) == "0009_reader_v5_opaque_progress"
        source_node_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspect(engine).get_indexes("LibrarySourceNode")
        }
        import_task_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspect(engine).get_indexes("LibraryImportTask")
        }
        assert source_node_indexes["LibrarySourceNode_parentId_idx"] == ("parentId",)
        assert import_task_indexes["LibraryImportTask_sourceNodeId_idx"] == (
            "sourceNodeId",
        )
    finally:
        engine.dispose()


def test_foreign_key_lookup_indexes_upgrade_from_previous_head(tmp_path) -> None:
    from alembic import command

    from app.db.runner import alembic_config_for_engine

    expected_indexes = {
        "BookDetailPreference": "BookDetailPreference_bookId_idx",
        "KindleSendTask": "KindleSendTask_resourceId_idx",
        "LibraryImportTask": "LibraryImportTask_resourceId_libraryId_idx",
        "LibraryOperation": "LibraryOperation_userId_idx",
        "LibraryResourceAsset": "LibraryResourceAsset_libraryId_idx",
        "MetadataLookupTask": "MetadataLookupTask_organizeJobId_idx",
        "MetadataWritebackOperation": ("MetadataWritebackOperation_lookupTaskId_idx"),
        "MetadataWritebackPreparation": (
            "MetadataWritebackPreparation_lookupTaskId_idx"
        ),
        "MetadataWritebackTarget": "MetadataWritebackTarget_assetId_idx",
        "ReaderBookmark": "ReaderBookmark_resourceId_idx",
        "ReaderProgressMutation": "ReaderProgressMutation_resourceId_idx",
        "Session": "Session_userId_idx",
    }
    engine = create_sqlite_engine(tmp_path / "foreign-key-index-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0007_source_node_lookup_indexes")

        for table_name, index_name in expected_indexes.items():
            assert index_name not in {
                index["name"] for index in inspect(engine).get_indexes(table_name)
            }

        runner_module.apply_schema(engine)
        assert _current_revision(engine) == "0009_reader_v5_opaque_progress"
        for table_name, index_name in expected_indexes.items():
            assert index_name in {
                index["name"] for index in inspect(engine).get_indexes(table_name)
            }
        kindle_indexes = {
            index["name"] for index in inspect(engine).get_indexes("KindleSendTask")
        }
        assert "KindleSendTask_assetId_idx" in kindle_indexes
        import_task_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspect(engine).get_indexes("LibraryImportTask")
        }
        assert import_task_indexes["LibraryImportTask_resourceId_libraryId_idx"] == (
            "resourceId",
            "libraryId",
        )
        _assert_all_foreign_keys_have_lookup_indexes(engine)
    finally:
        engine.dispose()


def test_scan_queue_migration_coalesces_existing_queued_tasks(tmp_path) -> None:
    from alembic import command

    from app.db.runner import alembic_config_for_engine

    engine = create_sqlite_engine(tmp_path / "upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_library_topology_baseline")
        with Session(engine) as session:
            session.add(
                Library(
                    id="scan-library",
                    name="Scan Library",
                    root_path=str(tmp_path / "books"),
                    organization_mode="FLAT",
                )
            )
            session.commit()
        legacy_tasks = Table(
            "LibraryImportTask",
            MetaData(),
            autoload_with=engine,
        )
        with engine.begin() as connection:
            connection.execute(
                legacy_tasks.insert(),
                [
                    {
                        "id": "queued-1",
                        "kind": "SCAN_LIBRARY",
                        "libraryId": "scan-library",
                        "state": "QUEUED",
                    },
                    {
                        "id": "queued-2",
                        "kind": "SCAN_LIBRARY",
                        "libraryId": "scan-library",
                        "state": "QUEUED",
                    },
                ],
            )

        runner_module.apply_schema(engine)
        runner_module.apply_schema(engine)

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(LibraryImportTask)
                    .where(
                        LibraryImportTask.library_id == "scan-library",
                        LibraryImportTask.kind == "SCAN_LIBRARY",
                        LibraryImportTask.state == "QUEUED",
                    )
                )
                == 1
            )
            migrated = session.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.library_id == "scan-library"
                )
            )
            assert migrated is not None
            assert migrated.missing_entry_policy == "PRESERVE"
        index_names = {
            index["name"] for index in inspect(engine).get_indexes("LibraryImportTask")
        }
        assert "LibraryImportTask_scan_queued_key" in index_names
        assert "LibraryImportTask_scan_running_key" in index_names
        assert "LibraryImportTask_sourceNodeId_idx" in index_names
        source_node_index_names = {
            index["name"] for index in inspect(engine).get_indexes("LibrarySourceNode")
        }
        assert "LibrarySourceNode_parentId_idx" in source_node_index_names
    finally:
        engine.dispose()


def test_apply_schema_rejects_former_development_revisions(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    retired_metadata = MetaData()
    alembic_version = Table(
        "alembic_version",
        retired_metadata,
        Column("version_num", String(191), nullable=False, primary_key=True),
    )
    try:
        for retired in (
            "0002_source_node_writeback",
            "0002_version_covers",
            "0003_readable_resource_overlay_schema",
        ):
            retired_metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(alembic_version.delete())
                connection.execute(alembic_version.insert().values(version_num=retired))
            with pytest.raises(RuntimeError, match="fresh installation"):
                runner_module.apply_schema(engine, settings)
            assert _current_revision(engine) == retired
            assert _application_tables(engine) == set()
            alembic_version.drop(engine)
    finally:
        engine.dispose()


def test_alembic_baseline_matches_sqlalchemy_metadata(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_seed_is_insert_only_and_safe_across_concurrent_sessions(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            system_name = db.get(SystemSetting, "systemName")
            douban = db.scalar(select(Source).where(Source.provider_type == "douban"))
            assert system_name is not None
            assert douban is not None
            system_name.value = "我的书库"
            douban.name = "自定义豆瓣"
            douban.enabled = False
            db.commit()

        def seed_once() -> None:
            with Session(engine) as db:
                seed_baseline_data(db)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _index: seed_once(), range(8)))

        with Session(engine) as db:
            server_identities = tuple(
                db.scalars(
                    select(SystemSetting.value).where(
                        SystemSetting.key == SERVER_IDENTITY_SETTING_KEY
                    )
                )
            )
            assert len(server_identities) == 1
            assert re.fullmatch(r"server_[0-9a-f]{32}", server_identities[0])
            assert db.get(SystemSetting, "systemName").value == "我的书库"
            douban = db.scalar(select(Source).where(Source.provider_type == "douban"))
            assert douban is not None
            assert (douban.name, douban.enabled) == ("自定义豆瓣", False)
            assert len(db.scalars(select(SystemSetting)).all()) == 3
            assert (
                len(db.scalars(select(Source).where(Source.kind == "metadata")).all())
                == 3
            )
    finally:
        engine.dispose()


def test_apply_schema_accepts_current_head_idempotently(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        expected_revision = head_revision(engine)

        runner_module.apply_schema(engine, settings)
        runner_module.apply_schema(engine, settings)

        assert _current_revision(engine) == expected_revision
        assert _application_tables(engine) == set(Base.metadata.tables)
        assert not (settings.database_path.parent / "migrations").exists()
    finally:
        engine.dispose()


def test_apply_schema_bootstraps_empty_in_memory_database() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        runner_module.apply_schema(engine)
        assert _application_tables(engine) == set(Base.metadata.tables)
        assert _current_revision(engine) == head_revision(engine)
    finally:
        engine.dispose()


def test_apply_schema_rejects_nonempty_unversioned_database(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    sentinel_metadata = MetaData()
    Table(
        "UnsupportedLegacyTable",
        sentinel_metadata,
        Column("id", Integer, primary_key=True),
    )
    try:
        sentinel_metadata.create_all(engine)
        with pytest.raises(RuntimeError, match="fresh installation"):
            runner_module.apply_schema(engine, settings)
        assert _current_revision(engine) is None
        assert "UnsupportedLegacyTable" in _application_tables(engine)
    finally:
        engine.dispose()


def test_apply_schema_retries_transient_database_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    original_apply = runner_module._apply_schema_once
    attempts = 0

    def apply_with_transient_lock(target_engine, target_settings):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError(
                "schema initialization",
                {},
                RuntimeError("database is locked"),
            )
        return original_apply(target_engine, target_settings)

    monkeypatch.setattr(runner_module, "_apply_schema_once", apply_with_transient_lock)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    try:
        runner_module.apply_schema(engine, settings)
        assert attempts == 2
        assert _current_revision(engine) == head_revision(engine)
    finally:
        engine.dispose()


def test_backup_uses_current_revision_and_restores_current_schema(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(SystemSetting(key="backup.guard", value="archived"))
            db.commit()
            backup = create_backup(db, settings)
            with zipfile.ZipFile(backup_path(settings, backup.id)) as archive:
                metadata = json.loads(archive.read("metadata.json"))
            assert metadata["version"] == 5
            assert metadata["databaseRevision"] == head_revision(engine)

            guard = db.get(SystemSetting, "backup.guard")
            assert guard is not None
            guard.value = "changed"
            db.commit()
            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            assert db.get(SystemSetting, "backup.guard").value == "archived"
    finally:
        engine.dispose()


@pytest.mark.parametrize("organization_mode", ("FLAT", "VOLUMES"))
def test_backup_restore_round_trip_preserves_fresh_source_topology(
    tmp_path, organization_mode: str
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        observed_at = datetime.now(UTC)
        library_id = "backup-topology-library"
        book_node_id = "backup-topology-book-node"
        resource_node_id = "backup-topology-resource-node"
        book_id = "backup-topology-book"
        resource_id = "backup-topology-resource"
        asset_id = "backup-topology-asset"
        with Session(engine) as db:
            db.add(
                Library(
                    id=library_id,
                    name="Backup topology",
                    root_path=str(tmp_path / "library"),
                    organization_mode=organization_mode,
                )
            )
            db.flush()
            book_node = LibrarySourceNode(
                id=book_node_id,
                library_id=library_id,
                relative_path="book/",
                path_key="v1:" + hashlib.sha256(b"book/").hexdigest(),
                name="book",
                physical_kind="DIRECTORY",
                observed_size_bytes=None,
                observed_mtime_ns=1,
                observed_at=observed_at,
            )
            resource_node = LibrarySourceNode(
                id=resource_node_id,
                library_id=library_id,
                parent_id=book_node_id,
                parent_physical_kind="DIRECTORY",
                relative_path="book/book.epub",
                path_key="v1:" + hashlib.sha256(b"book/book.epub").hexdigest(),
                name="book.epub",
                physical_kind="REGULAR_FILE",
                observed_size_bytes=3,
                observed_mtime_ns=1,
                observed_at=observed_at,
            )
            db.add_all([book_node, resource_node])
            db.flush()
            db.add(
                LibrarySourceNodeMetadata(
                    source_node_id=book_node_id,
                    title="Directory title",
                )
            )
            db.add_all(
                [
                    LibrarySourceNodeInterpretation(
                        source_node_id=book_node_id,
                        result="NODE_ONLY",
                        source="AUTO",
                    ),
                    LibrarySourceNodeInterpretation(
                        source_node_id=resource_node_id,
                        result="RESOURCE",
                        source="AUTO",
                        adapter_id="epub-file",
                        adapter_version="1",
                    ),
                ]
            )
            book = LibraryBook(
                id=book_id,
                library_id=library_id,
                source_node_id=book_node_id,
            )
            db.add(book)
            db.flush()
            db.add(
                LibraryBookMetadata(
                    book_id=book_id,
                    title="Backup topology book",
                    normalized_title="backup topology book",
                )
            )
            resource = LibraryReadableResource(
                id=resource_id,
                library_id=library_id,
                book_id=book_id,
                source_node_id=resource_node_id,
                adapter_id="epub-file",
                adapter_version="1",
                format="EPUB",
                enablement_state="ENABLED",
                import_state="READY",
            )
            db.add(resource)
            db.flush()
            db.add(
                LibraryReadableResourceMetadata(
                    resource_id=resource_id,
                    title="Backup topology resource",
                )
            )
            asset = LibraryResourceAsset(
                id=asset_id,
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=resource_node_id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            )
            db.add(asset)
            db.flush()
            db.add(
                LibraryResourceAssetMetadata(
                    asset_id=asset_id,
                    mime_type="application/epub+zip",
                )
            )
            db.add(
                LibraryImportTask(
                    id="backup-topology-import-task",
                    kind="IMPORT_ASSET",
                    library_id=library_id,
                    resource_id=resource_id,
                    source_node_id=resource_node_id,
                    role="PRIMARY",
                    state="SUCCEEDED",
                )
            )
            db.commit()

            backup = create_backup(db, settings)
            with zipfile.ZipFile(backup_path(settings, backup.id)) as archive:
                database_export = json.loads(
                    archive.read("database-export.json").decode("utf-8")
                )
                metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            assert metadata["version"] == 5
            assert database_export["sourceNodes"]
            assert database_export["sourceNodeMetadata"]
            assert database_export["sourceNodeInterpretations"]
            assert database_export["resourceAssetMetadata"]

            db.execute(
                LibrarySourceNodeMetadata.__table__.update()
                .where(LibrarySourceNodeMetadata.source_node_id == book_node_id)
                .values(title="changed after backup")
            )
            db.commit()
            restore_backup(db, settings, backup.id)

            restored_metadata = db.get(LibrarySourceNodeMetadata, book_node_id)
            assert restored_metadata is not None
            assert restored_metadata.title == "Directory title"
            assert db.get(LibrarySourceNode, resource_node_id) is not None
            assert db.get(LibraryResourceAssetMetadata, asset_id) is not None
    finally:
        engine.dispose()


def test_invalid_topology_backup_is_rejected_before_live_restore(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            db.add(SystemSetting(key="backup.sentinel", value="before"))
            db.commit()
            backup = create_backup(db, settings)

            backup_file = backup_path(settings, backup.id)
            with zipfile.ZipFile(backup_file) as archive:
                metadata_bytes = archive.read("metadata.json")
                database_export = json.loads(
                    archive.read("database-export.json").decode("utf-8")
                )
                settings_bytes = archive.read("settings.json")
            database_export["libraries"] = [{"id": "library-with-dangling-book"}]
            database_export["sourceNodes"] = []
            database_export["books"] = [
                {
                    "id": "book-with-dangling-source-node",
                    "libraryId": "library-with-dangling-book",
                    "sourceNodeId": "missing-source-node",
                }
            ]
            with zipfile.ZipFile(backup_file, "w") as archive:
                archive.writestr("metadata.json", metadata_bytes)
                archive.writestr(
                    "database-export.json",
                    json.dumps(database_export).encode("utf-8"),
                )
                archive.writestr("settings.json", settings_bytes)

            with pytest.raises(ValueError, match="BACKUP_FOREIGN_KEY_INVALID"):
                restore_backup(db, settings, backup.id)
            assert db.get(SystemSetting, "backup.sentinel").value == "before"
    finally:
        engine.dispose()


def test_final_identity_foreign_keys_point_to_target_entities(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        inspector = inspect(engine)

        def targets(table_name: str) -> set[tuple[tuple[str, ...], str]]:
            return {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            }

        expected = {
            "LibraryBookFacet": (("bookId",), "LibraryBook"),
            "LibraryReadableResourceFacet": (
                ("resourceId",),
                "LibraryReadableResource",
            ),
            "ShelfBook": (("bookId",), "LibraryBook"),
            "BookDetailPreference": (("bookId",), "LibraryBook"),
            "ReaderBookPreference": (("bookId",), "LibraryBook"),
            "ReaderProgressCursor": (("resourceId",), "LibraryReadableResource"),
            "ReaderResourceProgress": (("resourceId",), "LibraryReadableResource"),
            "ReaderProgressMutation": (("resourceId",), "LibraryReadableResource"),
            "ReaderBookmark": (("resourceId",), "LibraryReadableResource"),
            "ReadableResourceNavigationUnit": (
                ("resourceId",),
                "LibraryReadableResource",
            ),
            "LibraryResourceAssetNavigation": (
                ("assetId",),
                "LibraryResourceAsset",
            ),
            "KindleSendTask": (("bookId",), "LibraryBook"),
            "OrganizeJob": (("bookId",), "LibraryBook"),
            "MetadataLookupTask": (("bookId",), "LibraryBook"),
            "MetadataWritebackOperation": (("bookId",), "LibraryBook"),
            "MetadataWritebackPreparation": (("bookId",), "LibraryBook"),
        }
        for table_name, foreign_key in expected.items():
            assert foreign_key in targets(table_name), table_name

        for table_name in (
            "ReadableResourceNavigationUnit",
            "LibraryResourceAssetNavigation",
            "KindleSendTask",
            "OrganizeJob",
            "MetadataLookupTask",
            "MetadataWritebackOperation",
            "MetadataWritebackPreparation",
        ):
            assert (
                ("assetId",),
                "LibraryResourceAsset",
            ) in targets(table_name), table_name
    finally:
        engine.dispose()
