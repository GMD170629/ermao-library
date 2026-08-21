from __future__ import annotations

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db import runner as runner_module
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.runner import head_revision
from app.db.seed import seed_baseline_data
from app.db.sqlite import create_sqlite_engine
from app.models.import_pipeline import ImportTask, Source
from app.models.library import (
    Library,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import ReaderBookPreference, SystemSetting
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.modules.mobile.public import SERVER_IDENTITY_SETTING_KEY
from app.services.backup_service import backup_path, create_backup, restore_backup


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
        assert {
            "Library",
            "LibraryWork",
            "LibraryVersion",
            "LibraryVolume",
            "LibraryFile",
            "ImportScanJob",
            "ImportTask",
            "LibrarySourceNode",
            "LibraryBook",
            "LibraryReadableResource",
            "LibraryResourceAsset",
            "LibraryImportTask",
        } <= table_names
        assert {
            "LibraryImportRun",
            "ResourceCandidate",
            "AssetCandidate",
        }.isdisjoint(table_names)
        assert {
            "MonitorFolder",
            "UserMonitorFolderAccess",
            "LibraryMediaVersion",
            "DuplicateCandidate",
            "MediaVersionMigrationEvent",
            "UserMediaHistory",
        }.isdisjoint(table_names)

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
        assert all(
            organization_mode in library_checks
            for organization_mode in ("FLAT", "VOLUMES", "AUDIOBOOK")
        )

        work_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryWork")
        }
        version_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryVersion")
        }
        volume_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryVolume")
        }
        file_columns = {
            column["name"]: column for column in inspector.get_columns("LibraryFile")
        }
        assert work_columns["libraryId"]["nullable"] is False
        assert version_columns["workId"]["nullable"] is False
        assert version_columns["sourceKey"]["nullable"] is False
        assert "coverPath" in version_columns
        assert version_columns["coverPath"]["nullable"] is True
        assert version_columns["coverStatus"]["nullable"] is False
        assert volume_columns["versionId"]["nullable"] is False
        assert file_columns["volumeId"]["nullable"] is False
        assert "libraryId" not in volume_columns
        assert "monitorFolderId" not in volume_columns

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

        volume_foreign_keys = {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
            )
            for foreign_key in inspector.get_foreign_keys("LibraryVolume")
        }
        assert (("versionId",), "LibraryVersion") in volume_foreign_keys
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
    try:
        for retired in (
            "0002_version_covers",
            "0003_readable_resource_overlay_schema",
        ):
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
                connection.exec_driver_sql(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(191) NOT NULL PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    f"INSERT INTO alembic_version (version_num) VALUES ('{retired}')"
                )
            with pytest.raises(RuntimeError, match="fresh installation"):
                runner_module.apply_schema(engine, settings)
            assert _current_revision(engine) == retired
            assert _application_tables(engine) == set()
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


def test_backup_restore_preserves_import_task_json_metadata(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            original_metadata = {
                "title": "恢复前标题",
                "subjects": ["数据库", "备份"],
                "source": "PATH",
            }
            db.add(
                ImportTask(
                    id="backup-json-import-task",
                    origin="BACKUP_TEST",
                    status="COMPLETED",
                    source_path="/library/backup-test.epub",
                    source_key="backup-json-source-key",
                    recognized_metadata=original_metadata,
                )
            )
            db.commit()
            backup = create_backup(db, settings)

            task = db.get(ImportTask, "backup-json-import-task")
            assert task is not None
            task.recognized_metadata = {"title": "恢复后临时值"}
            db.commit()
            restored = restore_backup(db, settings, backup.id)

            assert restored["restored"] is True
            restored_task = db.get(ImportTask, "backup-json-import-task")
            assert restored_task is not None
            assert restored_task.recognized_metadata == original_metadata
    finally:
        engine.dispose()


def _seed_library_work(db: Session, *, work_id: str) -> LibraryWork:
    library = db.get(Library, "version-library")
    if library is None:
        library = Library(
            id="version-library",
            name="Version Library",
            root_path="/version-library",
            organization_mode="FLAT",
        )
        db.add(library)
        db.flush()
    work = LibraryWork(
        id=work_id,
        library_id=library.id,
        title="星海纪行",
        normalized_title="星海纪行",
        tags="[]",
    )
    db.add(work)
    db.flush()
    return work


def test_directory_version_identity_is_unique_within_each_work(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            first_work = _seed_library_work(db, work_id="work-a")
            second_work = _seed_library_work(db, work_id="work-b")
            db.add_all(
                [
                    LibraryVersion(
                        id="version-a",
                        work_id=first_work.id,
                        source_key="directory:version",
                    ),
                    LibraryVersion(
                        id="version-b",
                        work_id=second_work.id,
                        source_key="directory:version",
                    ),
                ]
            )
            db.commit()

            db.add(
                LibraryVersion(
                    id="version-a-duplicate",
                    work_id=first_work.id,
                    source_key="directory:version",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        engine.dispose()


def test_volume_belongs_to_directory_version_and_version_requires_work(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            work = _seed_library_work(db, work_id="work-volume")
            version = LibraryVersion(
                id="version-volume",
                work_id=work.id,
                source_key=IMPLICIT_VERSION_SOURCE_KEY,
            )
            db.add(version)
            db.flush()
            volume = LibraryVolume(
                id="volume-a",
                version_id=version.id,
                title="正文",
                format="EPUB",
                resource_key="directory:volume",
            )
            db.add(volume)
            db.commit()

            stored = db.get(LibraryVolume, volume.id)
            assert stored is not None
            assert stored.version_id == version.id

            db.add(
                LibraryVersion(
                    id="orphan-version",
                    work_id="missing-work",
                    source_key=IMPLICIT_VERSION_SOURCE_KEY,
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
    finally:
        engine.dispose()
