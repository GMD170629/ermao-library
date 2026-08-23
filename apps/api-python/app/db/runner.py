"""Alembic-backed schema bootstrap for fresh installations."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.core.config import Settings

LOGGER = logging.getLogger(__name__)
SCHEMA_LOCK_RETRY_SECONDS = 60.0


def alembic_config_for_engine(engine: Engine) -> Config:
    """Return Alembic Config bound to ``engine``'s SQLite database."""

    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "alembic")
    )
    database = engine.url.database
    if database:
        config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    else:
        # :memory: — URL alone is not enough; callers must pass connection via attributes.
        config.set_main_option(
            "sqlalchemy.url", engine.url.render_as_string(hide_password=False)
        )
    return config


def head_revision(engine: Engine | None = None) -> str:
    config = (
        alembic_config_for_engine(engine) if engine is not None else _default_config()
    )
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found {heads!r}")
    return heads[0]


def _default_config() -> Config:
    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "alembic")
    )
    return config


def _run_alembic(engine: Engine, fn) -> None:
    """Run an Alembic CLI command using ``engine``'s live connection."""

    config = alembic_config_for_engine(engine)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        fn(config)


def _schema_state(engine: Engine) -> tuple[str | None, set[str]]:
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
        table_names = set(sa_inspect(connection).get_table_names())
    table_names.discard("alembic_version")
    return revision, table_names


def _upgrade_head(engine: Engine) -> None:
    _run_alembic(engine, lambda config: command.upgrade(config, "head"))
    LOGGER.info("database alembic upgraded to head=%s", head_revision(engine))


def _unsupported_database_error(
    current_revision: str | None, head: str
) -> RuntimeError:
    if current_revision is None:
        return RuntimeError(
            "Existing database is not supported by this release. "
            "This release requires a fresh installation with an empty database."
        )
    return RuntimeError(
        f"Database revision {current_revision!r} is not supported by this release. "
        f"Expected {head!r}. This release requires a fresh installation."
    )


def _apply_schema_once(engine: Engine, _settings: Settings | None = None) -> None:
    current_revision, application_tables = _schema_state(engine)
    head = head_revision(engine)

    if not application_tables and current_revision is None:
        _upgrade_head(engine)
    elif current_revision == head:
        pass
    else:
        raise _unsupported_database_error(current_revision, head)

    with engine.connect() as connection:
        stamped = MigrationContext.configure(connection).get_current_revision()
        if stamped is None:
            raise RuntimeError("database migration did not record an alembic_version")


def apply_schema(engine: Engine, settings: Settings | None = None) -> None:
    """Create the current schema on an empty database, or accept the current HEAD."""

    deadline = time.monotonic() + SCHEMA_LOCK_RETRY_SECONDS
    retry_delay = 0.25
    while True:
        try:
            _apply_schema_once(engine, settings)
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            remaining = max(0.0, deadline - time.monotonic())
            delay = min(retry_delay, remaining)
            LOGGER.warning(
                "database is busy during schema initialization; retrying in %.2fs",
                delay,
            )
            time.sleep(delay)
            retry_delay = min(retry_delay * 2, 2.0)
