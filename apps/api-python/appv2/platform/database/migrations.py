from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def migrate(database_url: str, backend_root: Path) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            version = str(connection.execute(text("SHOW server_version")).scalar_one())
        if int(version.split(".", 1)[0]) != 18:
            raise RuntimeError(f"appv2 requires PostgreSQL 18.x; connected server is {version}")
    finally:
        engine.dispose()
    config = Config(backend_root / "alembic-v2.ini")
    command.upgrade(config, "head")
