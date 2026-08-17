"""Alembic runner for the independent current schema lineage."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from app.db.current.engine import canonical_database_path, create_current_engine
from app.db.current.lock import schema_lock

CURRENT_VERSION_TABLE = "alembic_version_v2"
CURRENT_ALEMBIC_INI = Path(__file__).parent.parent / "alembic_current" / "alembic.ini"


def current_alembic_config() -> Config:
    """Build an Alembic config that points only at current scripts."""

    config_path = CURRENT_ALEMBIC_INI.resolve()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.parent))
    return config


def upgrade_current_schema_unlocked(engine: Engine) -> None:
    """Apply current revisions using an already acquired schema lock."""

    config = current_alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def upgrade_current_schema(
    database_path: str | Path,
    *,
    lock_timeout_seconds: float = 30.0,
    engine_timeout_seconds: float = 30.0,
) -> None:
    """Apply the current Alembic head to the supplied database path.

    This function deliberately performs no legacy schema inspection, version
    detection, backup, migration, or rejection branch.
    """

    path = canonical_database_path(database_path)
    engine = create_current_engine(path, timeout_seconds=engine_timeout_seconds)
    try:
        with schema_lock(path, timeout_seconds=lock_timeout_seconds):
            upgrade_current_schema_unlocked(engine)
    finally:
        engine.dispose()
