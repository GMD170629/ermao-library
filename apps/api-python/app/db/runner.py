"""Alembic-backed schema migration runner for fresh, v14, and Alembic databases."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine

import app.models  # noqa: F401 — ensure metadata is complete
from app.core.config import Settings
from app.db.timestamp_triggers import ensure_timestamp_triggers

LOGGER = logging.getLogger(__name__)
SCHEMA_LOCK_RETRY_SECONDS = 60.0
BASELINE_USER_VERSION = 14


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
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        fn(config)


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _looks_like_baseline_schema(table_names: set[str]) -> bool:
    """True when declared squashed-baseline tables are already present."""

    required = ("User", "LibraryWork", "SystemHealthRun", "QueueControlOperation")
    return set(required).issubset(table_names)


def _schema_state(engine: Engine) -> tuple[str | None, set[str]]:
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
        table_names = set(sa_inspect(connection).get_table_names())
    table_names.discard("alembic_version")
    return revision, table_names


def _backup_before_migration(
    connection: sqlite3.Connection, settings: Settings, label: str
) -> None:
    backup_dir = settings.database_path.parent / "migrations"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"shuku-before-alembic-{label}.sqlite3"
    if backup_path.exists():
        return
    backup_connection = sqlite3.connect(backup_path)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    LOGGER.info("database migration backup created path=%s", backup_path)


def _stamp_head(engine: Engine) -> None:
    _run_alembic(engine, lambda config: command.stamp(config, "head"))
    LOGGER.info("database alembic version stamped head=%s", head_revision(engine))


def _upgrade_head(engine: Engine) -> None:
    _run_alembic(engine, lambda config: command.upgrade(config, "head"))
    LOGGER.info("database alembic upgraded to head=%s", head_revision(engine))


def _apply_schema_once(engine: Engine, settings: Settings | None = None) -> None:
    current_alembic, application_tables = _schema_state(engine)
    raw_connection = engine.raw_connection()
    try:
        driver_connection: sqlite3.Connection = raw_connection.driver_connection
        try:
            driver_connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            # :memory: with some pool configs may reject WAL; ignore.
            pass

        user_version = _user_version(driver_connection)
        has_tables = bool(application_tables)
        head = head_revision(engine)

        if current_alembic is not None:
            raw_connection.close()
            raw_connection = None
            _upgrade_head(engine)
        elif not has_tables:
            if settings is not None and engine.url.database not in (
                None,
                "",
                ":memory:",
            ):
                _backup_before_migration(driver_connection, settings, head)
            raw_connection.close()
            raw_connection = None
            _upgrade_head(engine)
        elif user_version == BASELINE_USER_VERSION or (
            user_version == 0 and _looks_like_baseline_schema(application_tables)
        ):
            # Stamp trusted v14 DBs, or test/create_all DBs that already match baseline.
            if settings is not None and engine.url.database not in (
                None,
                "",
                ":memory:",
            ):
                _backup_before_migration(driver_connection, settings, f"stamp-{head}")
            raw_connection.close()
            raw_connection = None
            _stamp_head(engine)
        elif user_version < BASELINE_USER_VERSION:
            raise RuntimeError(
                f"不支持 pre-v14 数据库（user_version={user_version}）；"
                "请先使用支持旧版本迁移的应用升级到 v14"
            )
        else:
            raise RuntimeError(
                f"数据库版本 {user_version} 高于当前应用支持的版本 {BASELINE_USER_VERSION}，请升级应用"
            )
    finally:
        if raw_connection is not None:
            raw_connection.close()

    with engine.begin() as connection:
        ensure_timestamp_triggers(connection)
        stamped = MigrationContext.configure(connection).get_current_revision()
        if stamped is None:
            raise RuntimeError("database migration did not record an alembic_version")


def apply_schema(engine: Engine, settings: Settings | None = None) -> None:
    """Apply Alembic migrations for supported databases and timestamp triggers."""

    deadline = time.monotonic() + SCHEMA_LOCK_RETRY_SECONDS
    retry_delay = 0.25
    while True:
        try:
            _apply_schema_once(engine, settings)
            return
        except sqlite3.OperationalError as exc:
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
