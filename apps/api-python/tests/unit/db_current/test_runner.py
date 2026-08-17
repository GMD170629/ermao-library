from __future__ import annotations

from pathlib import Path

from sqlalchemy import MetaData, Table, inspect, select

from app.db.current.engine import create_current_engine
from app.db.current.runner import upgrade_current_schema


def test_fresh_current_upgrade_uses_only_current_version_table(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"

    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "alembic_version_v2" in tables
        assert "alembic_version" not in tables
    finally:
        engine.dispose()


def test_current_upgrade_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"

    upgrade_current_schema(database_path)
    upgrade_current_schema(database_path)

    engine = create_current_engine(database_path)
    try:
        version_table = Table(
            "alembic_version_v2",
            MetaData(),
            autoload_with=engine,
        )
        with engine.connect() as connection:
            versions = connection.scalars(select(version_table.c.version_num)).all()
        assert versions == ["0002_catalog_scan_topology"]
    finally:
        engine.dispose()
