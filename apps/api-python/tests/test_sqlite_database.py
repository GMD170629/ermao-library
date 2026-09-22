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
    insert,
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
            "scanScopes",
            "bookMetadataRevision",
            "rerunRequested",
            "resourceAnchorNodeId",
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
                model_key = next(
                    constraint
                    for constraint in Base.metadata.tables[
                        table_name
                    ].foreign_key_constraints
                    if tuple(column.name for column in constraint.columns)
                    == tuple(foreign_key["constrained_columns"])
                )
                assert foreign_key["options"].get("onupdate") == model_key.onupdate, (
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
                model_default = Base.metadata.tables[
                    table_name
                ].c.createdAt.server_default
                if model_default is None:
                    assert created_at["default"] is None, table_name
                else:
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
    assert len(revisions) == 29
    assert script.get_heads() == ["0029_file_deletions"]
    assert head_revision() == "0029_file_deletions"
    assert [revision.revision for revision in revisions] == [
        "0029_file_deletions",
        "0028_automation_capabilities",
        "0027_automation_uploads",
        "0026_automation_grant_secrets",
        "0025_standard_writeback_plans",
        "0024_file_move_recovery_limits",
        "0023_file_move_operations",
        "0022_automation_receipts",
        "0021_automation_grants",
        "0020_recheck_scan_gaps",
        "0019_backfill_scan_gaps",
        "0018_library_import_scan_gaps",
        "0017_reset_default_cover_paths",
        "0016_library_sort_order",
        "0015_scan_context_version",
        "0014_audio_resource_tasks",
        "0013_image_resource_tasks",
        "0012_resource_import_tasks",
        "0011_incremental_library_scan",
        "0010_book_metadata_completion",
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
    assert [revision.down_revision for revision in revisions] == [
        revision.revision for revision in revisions[1:]
    ] + [None]


def test_fresh_baseline_contains_source_node_writeback_schema(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        runner_module.apply_schema(engine, settings)
        assert _current_revision(engine) == "0029_file_deletions"
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
        assert _current_revision(engine) == "0029_file_deletions"
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
        assert _current_revision(engine) == "0029_file_deletions"
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
            old_library = Table(
                "Library", MetaData(), autoload_with=session.connection()
            )
            session.execute(
                old_library.insert().values(
                    id="scan-library",
                    name="Scan Library",
                    rootPath=str(tmp_path / "books"),
                    organizationMode="FLAT",
                    enabled=True,
                    updatedAt=int(datetime.now(UTC).timestamp() * 1000),
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
            assert migrated.scan_scopes is None
            library = session.get(Library, "scan-library")
            assert library is not None and library.allow_empty_library_cleanup is False
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


@pytest.mark.parametrize("interrupted_upgrade", [False, True])
def test_resource_tasks_upgrade_preserves_assets_and_pending_work(
    tmp_path, interrupted_upgrade
) -> None:
    from alembic import command
    from sqlalchemy import event

    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.db.runner import alembic_config_for_engine
    from app.modules.imports.application.readable_resource.continue_import import (
        ContinueImportTask,
    )
    from app.modules.library.infrastructure.readable_resource_schema import (
        LibraryReadableResourceMetadata,
        LibraryResourceAsset,
    )
    from app.modules.library.public import SourceNodeRelativePath

    engine = create_sqlite_engine(tmp_path / "resource-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    root = tmp_path / "books"
    root.mkdir()
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0011_incremental_library_scan")
        metadata = MetaData()
        names = (
            "Library",
            "LibrarySourceNode",
            "LibraryBook",
            "LibraryBookMetadata",
            "LibraryReadableResource",
            "LibraryReadableResourceMetadata",
            "LibraryResourceAsset",
            "LibraryImportTask",
        )
        tables = {name: Table(name, metadata, autoload_with=engine) for name in names}
        with engine.begin() as connection:
            connection.execute(
                tables["Library"]
                .insert()
                .values(
                    id="lib",
                    name="Library",
                    rootPath=str(root),
                    organizationMode="FLAT",
                    updatedAt=1,
                )
            )
            for index, state in enumerate(("QUEUED", "RUNNING", "FAILED", "SUCCEEDED")):
                node_id, resource_id, book_id, asset_id = (
                    f"{prefix}-{index}"
                    for prefix in ("node", "resource", "book", "asset")
                )
                filename = f"{index}.txt"
                (root / filename).write_text("fixture publication")
                stat = (root / filename).stat()
                connection.execute(
                    tables["LibrarySourceNode"]
                    .insert()
                    .values(
                        id=node_id,
                        libraryId="lib",
                        relativePath=filename,
                        pathKey=SourceNodeRelativePath(filename).path_key,
                        name=filename,
                        physicalKind="REGULAR_FILE",
                        observedSizeBytes=stat.st_size,
                        observedMtimeNs=stat.st_mtime_ns,
                        observedAt=1,
                        updatedAt=1,
                    )
                )
                connection.execute(
                    tables["LibraryBook"]
                    .insert()
                    .values(
                        id=book_id, libraryId="lib", sourceNodeId=node_id, updatedAt=1
                    )
                )
                connection.execute(
                    tables["LibraryBookMetadata"]
                    .insert()
                    .values(
                        bookId=book_id,
                        title="Protected",
                        normalizedTitle="protected",
                        updatedAt=1,
                    )
                )
                connection.execute(
                    tables["LibraryReadableResource"]
                    .insert()
                    .values(
                        id=resource_id,
                        libraryId="lib",
                        bookId=book_id,
                        sourceNodeId=node_id,
                        adapterId="txt",
                        adapterVersion="1",
                        format="TXT",
                        importState="READY",
                        updatedAt=1,
                    )
                )
                connection.execute(
                    tables["LibraryReadableResourceMetadata"]
                    .insert()
                    .values(
                        resourceId=resource_id,
                        title="Curated title",
                        protectedFields='["title"]',
                        updatedAt=1,
                    )
                )
                connection.execute(
                    tables["LibraryResourceAsset"]
                    .insert()
                    .values(
                        id=asset_id,
                        libraryId="lib",
                        resourceId=resource_id,
                        sourceNodeId=node_id,
                        role="PRIMARY",
                        importState="READY",
                        updatedAt=1,
                    )
                )
                connection.execute(
                    tables["LibraryImportTask"]
                    .insert()
                    .values(
                        id=f"task-{index}",
                        kind="IMPORT_ASSET",
                        libraryId="lib",
                        resourceId=resource_id,
                        sourceNodeId=node_id,
                        role="PRIMARY",
                        state=state,
                    )
                )
        if interrupted_upgrade:

            def interrupt(conn, cursor, statement, parameters, context, executemany):
                if 'ADD COLUMN "processedSourceVersion"' in statement:
                    raise RuntimeError("interrupted upgrade")

            event.listen(engine, "after_cursor_execute", interrupt)
            try:
                with pytest.raises(RuntimeError, match="interrupted upgrade"):
                    runner_module.apply_schema(engine)
            finally:
                event.remove(engine, "after_cursor_execute", interrupt)
        runner_module.apply_schema(engine)
        runner_module.apply_schema(engine)
        with Session(engine) as db:
            tasks = db.scalars(
                select(LibraryImportTask).order_by(LibraryImportTask.id)
            ).all()
            assert [task.kind for task in tasks] == ["IMPORT_RESOURCE"] * 3 + [
                "IMPORT_ASSET"
            ]
            assert [task.state for task in tasks] == [
                "QUEUED",
                "RUNNING",
                "FAILED",
                "SUCCEEDED",
            ]
            assert all(
                asset.processed_source_version is None
                for asset in db.scalars(select(LibraryResourceAsset))
            )
            assert all(
                item.title == "Curated title"
                for item in db.scalars(select(LibraryReadableResourceMetadata))
            )
            pipeline = build_readable_resource_pipeline(db)
            worker = build_readable_resource_worker(pipeline)
            assert worker.startup() == 1
            for task_id in ("task-1", "task-2"):
                pipeline.continue_import.execute(ContinueImportTask(task_id))
            for _ in range(20):
                if worker.process_once() == "idle":
                    break
            db.expire_all()
            assert all(
                db.get(LibraryImportTask, f"task-{index}").state == "SUCCEEDED"
                for index in range(4)
            )
            assert set(db.scalars(select(LibraryResourceAsset.id))) == {
                f"asset-{index}" for index in range(4)
            }
            assert (
                db.get(LibraryResourceAsset, "asset-0").processed_source_version
                is not None
            )
            assert (
                db.get(LibraryResourceAsset, "asset-3").processed_source_version is None
            )
            assert all(
                item.title == "Curated title"
                for item in db.scalars(select(LibraryReadableResourceMetadata))
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("media", ["image", "audio"])
def test_directory_legacy_tasks_upgrade_keeps_asset_ids_and_progress(
    tmp_path, monkeypatch, media
):
    from alembic import command

    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.db.runner import alembic_config_for_engine
    from app.models import LibraryImportTask, ReaderResourceProgress, User
    from app.modules.library.public import SourceNodeRelativePath

    engine = create_sqlite_engine(tmp_path / "images.sqlite3")
    settings = Settings(storage_root=str(tmp_path / "storage"))
    root = tmp_path / "books"
    root.mkdir()
    folder = root / "Images"
    folder.mkdir()
    config = alembic_config_for_engine(engine)
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(
                config,
                "0011_incremental_library_scan",
            )
        old_tasks = Table("LibraryImportTask", MetaData(), autoload_with=engine)
        old_library = Table("Library", MetaData(), autoload_with=engine)
        with Session(engine) as db:
            db.execute(
                old_library.insert().values(
                    id="lib",
                    name="Images",
                    rootPath=str(root),
                    organizationMode="FLAT",
                    enabled=True,
                    updatedAt=int(datetime.now(UTC).timestamp() * 1000),
                )
            )
            db.add(
                User(
                    id="user",
                    email="reader@example.test",
                    name="Reader",
                    password_hash="test-only",
                )
            )
            db.commit()
            db.add(
                LibrarySourceNode(
                    id="anchor",
                    library_id="lib",
                    relative_path="Images",
                    path_key=SourceNodeRelativePath("Images").path_key,
                    name="Images",
                    physical_kind="DIRECTORY",
                    observed_mtime_ns=0,
                    observed_at=datetime.now(UTC),
                )
            )
            db.commit()
            db.add(LibraryBook(id="book", library_id="lib", source_node_id="anchor"))
            db.commit()
            db.add(
                LibraryBookMetadata(
                    book_id="book", title="Images", normalized_title="images"
                )
            )
            db.execute(
                insert(LibraryReadableResource).values(
                    id="resource",
                    library_id="lib",
                    book_id="book",
                    source_node_id="anchor",
                    adapter_id="image-directory"
                    if media == "image"
                    else "audiobook-directory",
                    adapter_version="1",
                    format="IMAGE_DIR" if media == "image" else "AUDIOBOOK_DIR",
                )
            )
            db.commit()
            protected_cover = settings.resolved_storage_root / "covers/protected.png"
            protected_cover.parent.mkdir(parents=True, exist_ok=True)
            protected_cover.write_bytes(b"user-owned-cover")
            db.add(
                LibraryReadableResourceMetadata(
                    resource_id="resource",
                    title="User title",
                    cover_path="covers/protected.png",
                    protected_fields='["title","cover_path"]',
                )
            )
            db.add(
                ReaderResourceProgress(
                    id="progress",
                    user_id="user",
                    resource_id="resource",
                    reader_type="comic" if media == "image" else "audio",
                    position="2",
                    extra='{"assetId":"asset-2"}',
                )
            )
            for index, state in enumerate(
                ("QUEUED", "FAILED", "RUNNING", "SUCCEEDED"), start=1
            ):
                name = f"{index}.png" if media == "image" else f"{index}.mp3"
                (folder / name).write_bytes(
                    b"readable image file; optional artwork unavailable"
                )
                stat = (folder / name).stat()
                db.add(
                    LibrarySourceNode(
                        id=f"node-{index}",
                        library_id="lib",
                        parent_id="anchor",
                        parent_physical_kind="DIRECTORY",
                        relative_path=f"Images/{name}",
                        path_key=SourceNodeRelativePath(f"Images/{name}").path_key,
                        name=name,
                        physical_kind="REGULAR_FILE",
                        observed_size_bytes=stat.st_size,
                        observed_mtime_ns=stat.st_mtime_ns,
                        observed_at=datetime.now(UTC),
                    )
                )
            db.commit()
            for index, state in enumerate(
                ("QUEUED", "FAILED", "RUNNING", "SUCCEEDED"), start=1
            ):
                db.execute(
                    insert(LibraryResourceAsset).values(
                        id=f"asset-{index}",
                        library_id="lib",
                        resource_id="resource",
                        source_node_id=f"node-{index}",
                        role="PAGE" if media == "image" else "TRACK",
                        import_state="READY",
                    )
                )
                db.execute(
                    old_tasks.insert().values(
                        id=f"task-{index}",
                        kind="IMPORT_ASSET",
                        libraryId="lib",
                        resourceId="resource",
                        sourceNodeId=f"node-{index}",
                        role="PAGE" if media == "image" else "TRACK",
                        state=state,
                    )
                )
            db.commit()
        runner_module.apply_schema(engine)
        runner_module.apply_schema(engine)
        with Session(engine) as db:
            tasks = db.scalars(
                select(LibraryImportTask).where(LibraryImportTask.state != "SUCCEEDED")
            ).all()
            assert len(tasks) == 1
            assert tasks[0].kind == "IMPORT_RESOURCE"
            assert tasks[0].source_node_id == "anchor" and tasks[0].role is None
            assert all(
                a.processed_source_version is None
                for a in db.scalars(select(LibraryResourceAsset))
            )
            if media == "audio":
                from app.modules.imports.application.audio_types import (
                    AudioFileMetadata,
                )
                from app.modules.imports.infrastructure.audio_metadata_inspector import (
                    BoundedAudioMetadataInspector,
                )

                def inspect_audio(self, path):
                    return AudioFileMetadata(
                        path,
                        path.stem,
                        None,
                        None,
                        None,
                        3000,
                        "mp3",
                        None,
                        None,
                        None,
                        1,
                        int(path.stem),
                    )

                monkeypatch.setattr(
                    BoundedAudioMetadataInspector, "inspect", inspect_audio
                )
            pipeline = build_readable_resource_pipeline(db, settings)
            assert build_readable_resource_worker(pipeline).process_once() == "ok"
            assert {a.id for a in db.scalars(select(LibraryResourceAsset))} == {
                "asset-1",
                "asset-2",
                "asset-3",
                "asset-4",
            }
            protected = db.get(LibraryReadableResourceMetadata, "resource")
            assert (protected.title, protected.cover_path) == (
                "User title",
                "covers/protected.png",
            )
            assert protected_cover.read_bytes() == b"user-owned-cover"
            assert db.get(LibraryImportTask, "task-4").state == "SUCCEEDED"
            assert (
                db.get(ReaderResourceProgress, "progress").extra
                == '{"assetId":"asset-2"}'
            )
            assert db.get(ReaderResourceProgress, "progress").resource_id == "resource"
    finally:
        engine.dispose()


def test_fixture_sessions_do_not_share_transactions(db_session):
    db_session.add(
        Library(
            id="isolated-library",
            name="Isolated",
            root_path="/isolated",
            organization_mode="FLAT",
        )
    )
    db_session.flush()
    with Session(db_session.get_bind()) as background:
        assert background.scalar(select(1)) == 1
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Library, "isolated-library") is not None
