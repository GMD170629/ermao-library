from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Column,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    select,
    update,
)

from app.db.runner import _run_alembic, head_revision
from app.db.sqlite import create_sqlite_engine


def _upgrade(engine: Engine, revision: str) -> None:
    _run_alembic(engine, lambda config: command.upgrade(config, revision))


def _schema_fingerprint(engine: Engine) -> tuple[object, ...]:
    inspector = inspect(engine)
    tables: list[object] = []
    for table_name in sorted(
        name for name in inspector.get_table_names() if name != "alembic_version"
    ):
        columns = tuple(
            (
                column["name"],
                str(column["type"]),
                bool(column["nullable"]),
                column.get("default"),
                int(column.get("primary_key") or 0),
            )
            for column in inspector.get_columns(table_name)
        )
        primary_key = inspector.get_pk_constraint(table_name)
        foreign_keys = tuple(
            sorted(
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key.get("name"),
                    tuple(sorted((foreign_key.get("options") or {}).items())),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            )
        )
        unique_constraints = tuple(
            sorted(
                (tuple(constraint["column_names"]), constraint.get("name"))
                for constraint in inspector.get_unique_constraints(table_name)
            )
        )
        indexes = tuple(
            sorted(
                (
                    tuple(index["column_names"]),
                    bool(index["unique"]),
                    index["name"],
                    str((index.get("dialect_options") or {}).get("sqlite_where")),
                )
                for index in inspector.get_indexes(table_name)
            )
        )
        checks = tuple(
            sorted(
                (constraint.get("sqltext"), constraint.get("name"))
                for constraint in inspector.get_check_constraints(table_name)
            )
        )
        tables.append(
            (
                table_name,
                columns,
                tuple(primary_key.get("constrained_columns") or ()),
                primary_key.get("name"),
                foreign_keys,
                unique_constraints,
                indexes,
                checks,
            )
        )
    return tuple(tables)


def test_0008_enables_new_audio_extensions_once_for_existing_preferences(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "audio-preferences.sqlite3")
    try:
        _upgrade(engine, "0007_media_versions_contract")
        settings = Table("SystemSetting", MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                settings.insert().values(
                    key="import.allowedExtensions",
                    value=json.dumps([".epub", ".mp3"]),
                    createdAt=1,
                    updatedAt=1,
                )
            )
        _upgrade(engine, "head")
        with engine.begin() as connection:
            migrated = json.loads(
                connection.scalar(
                    select(settings.c.value).where(
                        settings.c.key == "import.allowedExtensions"
                    )
                )
            )
            assert migrated[:2] == [".epub", ".mp3"]
            assert {".flac", ".opus", ".wma", ".xma"}.issubset(migrated)
            connection.execute(
                update(settings)
                .where(settings.c.key == "import.allowedExtensions")
                .values(
                    value=json.dumps([item for item in migrated if item != ".flac"])
                )
            )
        _upgrade(engine, "head")
        with engine.connect() as connection:
            retained = json.loads(
                connection.scalar(
                    select(settings.c.value).where(
                        settings.c.key == "import.allowedExtensions"
                    )
                )
            )
            assert ".flac" not in retained
    finally:
        engine.dispose()


def _make_v14_shape_diverge(engine: Engine) -> None:
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table(
            "DownloadTask", recreate="always"
        ) as batch_operations:
            batch_operations.alter_column(
                "status",
                existing_type=String(length=32),
                type_=Text(),
                existing_nullable=False,
            )
        with operations.batch_alter_table(
            "ReaderBookmark", recreate="always"
        ) as batch_operations:
            constraint_name = "ReaderBookmark_user_edition_fingerprint_bookmark_key"
            batch_operations.drop_constraint(constraint_name, type_="unique")
            batch_operations.create_index(
                constraint_name,
                ["userId", "editionId", "contentFingerprint", "bookmarkId"],
                unique=True,
            )


def test_0004_produces_identical_schema_from_distinct_0003_shapes(
    tmp_path: Path,
) -> None:
    canonical = create_sqlite_engine(tmp_path / "canonical.sqlite3")
    legacy = create_sqlite_engine(tmp_path / "legacy.sqlite3")
    try:
        for engine in (canonical, legacy):
            _upgrade(engine, "0003_import_work_queue")
        _make_v14_shape_diverge(legacy)
        assert _schema_fingerprint(canonical) != _schema_fingerprint(legacy)

        for engine in (canonical, legacy):
            _upgrade(engine, "0004_schema_normalization")

        assert _schema_fingerprint(canonical) == _schema_fingerprint(legacy)

        for engine in (canonical, legacy):
            _upgrade(engine, "head")
            assert head_revision(engine) == "0013_local_metadata_resolution"

        assert _schema_fingerprint(canonical) == _schema_fingerprint(legacy)
    finally:
        canonical.dispose()
        legacy.dispose()


def test_0004_rejects_partially_applied_predecessor_without_repairing_it(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "partial.sqlite3")
    try:
        _upgrade(engine, "0003_import_work_queue")
        partial_table = Table(
            "PartiallyAppliedMigration",
            MetaData(),
            Column("id", Integer(), primary_key=True),
        )
        partial_table.create(engine)
        fingerprint_before = _schema_fingerprint(engine)

        with pytest.raises(RuntimeError, match="intact v14/0003"):
            _upgrade(engine, "0004_schema_normalization")

        assert _schema_fingerprint(engine) == fingerprint_before
        with engine.connect() as connection:
            assert (
                MigrationContext.configure(connection).get_current_revision()
                == "0003_import_work_queue"
            )
    finally:
        engine.dispose()
