from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.dialects import sqlite

from app.db.current.engine import create_current_engine
from app.db.current.registry import current_metadata
from app.db.current.runner import current_alembic_config, upgrade_current_schema


def _migration_metadata():
    return import_module(
        "app.db.alembic_current.versions.0001_system_and_catalog_core"
    ).metadata


def _foreign_keys(table):
    return sorted(
        tuple(
            (element.parent.name, element.target_fullname, element.ondelete)
            for element in constraint.elements
        )
        for constraint in table.foreign_key_constraints
    )


def _unique_constraints(table):
    return sorted(
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )


def _indexes(table):
    return sorted(
        (
            index.name,
            index.unique,
            tuple(
                getattr(expression, "name", str(expression))
                for expression in index.expressions
            ),
        )
        for index in table.indexes
    )


def _compiled_expression(expression) -> str:
    return str(
        expression.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _check_constraints(table):
    return sorted(
        (constraint.name, _compiled_expression(constraint.sqltext))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )


def _index_predicates(table):
    return sorted(
        (
            index.name,
            _compiled_expression(predicate) if predicate is not None else None,
        )
        for index in table.indexes
        for predicate in [index.dialect_options["sqlite"].get("where")]
    )


def test_current_migration_matches_runtime_table_shape() -> None:
    runtime = current_metadata()
    migration = _migration_metadata()

    assert set(migration.tables) == set(runtime.tables)
    for table_name, runtime_table in runtime.tables.items():
        migration_table = migration.tables[table_name]
        assert [column.name for column in migration_table.columns] == [
            column.name for column in runtime_table.columns
        ]
        assert [
            (column.name, str(column.type), column.nullable, column.primary_key)
            for column in migration_table.columns
        ] == [
            (column.name, str(column.type), column.nullable, column.primary_key)
            for column in runtime_table.columns
        ]
        assert [
            (
                column.name,
                str(column.server_default.arg) if column.server_default else None,
            )
            for column in migration_table.columns
        ] == [
            (
                column.name,
                str(column.server_default.arg) if column.server_default else None,
            )
            for column in runtime_table.columns
        ]
        assert _foreign_keys(migration_table) == _foreign_keys(runtime_table)
        assert _unique_constraints(migration_table) == _unique_constraints(
            runtime_table
        )
        assert _indexes(migration_table) == _indexes(runtime_table)
        assert _check_constraints(migration_table) == _check_constraints(runtime_table)
        assert _index_predicates(migration_table) == _index_predicates(runtime_table)


def test_current_migration_does_not_cross_runtime_or_sql_boundaries() -> None:
    revision_path = (
        Path(__file__).parents[3]
        / "app"
        / "db"
        / "alembic_current"
        / "versions"
        / "0001_system_and_catalog_core.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    for forbidden in (
        "app.modules",
        "app.models",
        "sqlite3",
        "sqlalchemy.text",
        "exec_driver_sql",
        "cursor(",
    ):
        assert forbidden not in source

    env_source = (revision_path.parent.parent / "env.py").read_text(encoding="utf-8")
    assert "current_metadata" not in env_source
    assert "app.modules" not in env_source
    assert "app.db.current.registry" not in env_source


def test_fresh_upgrade_does_not_import_runtime_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith(("app.modules", "app.models")):
            raise AssertionError(f"runtime import crossed migration boundary: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    upgrade_current_schema(tmp_path / "current.sqlite3")


def test_upgrade_recovers_missing_index_after_partial_ddl(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    migration = _migration_metadata()
    engine = create_current_engine(database_path)
    try:
        migration.create_all(engine)
        index = next(
            index
            for index in migration.tables["LibrarySourceEntry"].indexes
            if index.name == "LibrarySourceEntry_active_slot_idx"
        )
        index.drop(engine, checkfirst=True)
        assert "LibrarySourceEntry_active_slot_idx" not in {
            index["name"] for index in inspect(engine).get_indexes("LibrarySourceEntry")
        }
    finally:
        engine.dispose()

    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        assert "LibrarySourceEntry_active_slot_idx" in {
            index["name"] for index in inspect(engine).get_indexes("LibrarySourceEntry")
        }
    finally:
        engine.dispose()


def test_current_downgrade_is_rejected_without_mutating_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        before_tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            config = current_alembic_config()
            config.attributes["connection"] = connection
            with pytest.raises(
                NotImplementedError,
                match="current schema lineage is append-only; downgrade is unsupported",
            ):
                command.downgrade(config, "base")

        assert set(inspect(engine).get_table_names()) == before_tables
        version_table = Table("alembic_version_v2", MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            assert connection.scalars(select(version_table.c.version_num)).all() == [
                "0001_system_and_catalog_core"
            ]
    finally:
        engine.dispose()


def test_offline_current_downgrade_emits_no_destructive_sql(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(
        NotImplementedError,
        match="current schema lineage is append-only; downgrade is unsupported",
    ):
        command.downgrade(current_alembic_config(), "head:base", sql=True)

    output = capsys.readouterr().out
    assert "DROP TABLE" not in output
    assert "DELETE FROM alembic_version_v2" not in output


def test_offline_upgrade_emits_each_index_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(current_alembic_config(), "head", sql=True)
    output = capsys.readouterr().out

    assert "SELECT" not in output
    assert "CREATE TABLE alembic_version_v2" in output
    assert "INSERT INTO alembic_version_v2" in output

    for table in _migration_metadata().tables.values():
        for index in table.indexes:
            assert output.count(f'INDEX "{index.name}"') == 1
