"""The library sort-order migration backfills the previous display order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic import command

from app.core.config import Settings
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine

_PREVIOUS_REVISION = "0015_scan_context_version"


def _engine(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_sqlite_engine(settings.database_path)


def _library_table() -> sa.TableClause:
    return sa.table(
        "Library",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("rootPath", sa.String),
        sa.column("organizationMode", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("createdAt", sa.BigInteger),
        sa.column("updatedAt", sa.BigInteger),
        sa.column("sortOrder", sa.Integer),
    )


def _row(library_id: str, created_at: datetime) -> dict[str, object]:
    stamp = int(created_at.timestamp() * 1000)
    return {
        "id": library_id,
        "name": library_id,
        "rootPath": f"/{library_id}",
        "organizationMode": "FLAT",
        "enabled": True,
        "createdAt": stamp,
        "updatedAt": stamp,
    }


def test_upgrade_backfills_newest_first_and_is_reentrant(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    config = alembic_config_for_engine(engine)
    command.upgrade(config, _PREVIOUS_REVISION)
    library = _library_table()
    base = datetime(2024, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(library),
            [
                _row("oldest", base),
                _row("middle", base + timedelta(minutes=1)),
                _row("newest", base + timedelta(minutes=2)),
            ],
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        orders = dict(
            connection.execute(sa.select(library.c.id, library.c.sortOrder)).all()
        )
    assert orders == {"newest": 1, "middle": 2, "oldest": 3}


def test_downgrade_removes_the_sort_order_column(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    config = alembic_config_for_engine(engine)
    command.upgrade(config, "head")

    command.downgrade(config, _PREVIOUS_REVISION)

    columns = {
        column["name"] for column in sa.inspect(engine).get_columns("Library")
    }
    assert "sortOrder" not in columns
