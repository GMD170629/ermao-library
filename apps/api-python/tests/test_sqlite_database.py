from __future__ import annotations

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

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
from app.models.import_pipeline import Source
from app.models.library import Library
from app.models.settings import ReaderBookPreference, SystemSetting
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY
from app.services.backup_service import backup_path, create_backup, restore_backup


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
            "ReadableResourceNavigationUnit",
            "PublicationNavigationCache",
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
        import_task_indexes = {
            index["name"] for index in inspector.get_indexes("LibraryImportTask")
        }
        assert "LibraryImportTask_import_asset_key" in import_task_indexes
        assert "LibraryImportTask_queued_createdAt_idx" in import_task_indexes

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
                "workDetail.tabOrder": '["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"]',
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


def test_alembic_script_directory_has_single_fresh_baseline_head() -> None:
    from alembic.script import ScriptDirectory

    from app.db.runner import alembic_config_for_engine, head_revision

    config = alembic_config_for_engine(create_engine("sqlite+pysqlite:///:memory:"))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    assert len(revisions) == 1
    assert script.get_heads() == ["0001_library_topology_baseline"]
    assert head_revision() == "0001_library_topology_baseline"
    assert revisions[0].revision == "0001_library_topology_baseline"
    assert revisions[0].down_revision is None


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
            "0002_version_covers",
            "0003_readable_resource_overlay_schema",
        ):
            retired_metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(alembic_version.delete())
                connection.execute(
                    alembic_version.insert().values(version_num=retired)
                )
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
            assert len(db.scalars(select(SystemSetting)).all()) == 4
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
            assert metadata["version"] == 3
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
            "PublicationNavigationCache": (
                ("resourceId",),
                "LibraryReadableResource",
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
            "PublicationNavigationCache",
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
