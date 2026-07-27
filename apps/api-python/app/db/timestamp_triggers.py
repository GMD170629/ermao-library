from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection


def _timestamp_columns(connection: Connection, table: str) -> list[str]:
    return [
        str(column["name"])
        for column in inspect(connection).get_columns(table)
        if str(column["name"]).endswith("At") or str(column["name"]).endswith("_at")
    ]


def _timestamp_trigger_expression(column: str) -> str:
    value = f"CAST(NEW.{column} AS TEXT)"
    numeric = f"TRIM({value}) NOT GLOB '*[^0-9]*' AND LENGTH(TRIM({value})) > 0"
    return (
        "CASE "
        f"WHEN NEW.{column} IS NULL THEN NULL "
        f"WHEN {numeric} THEN CASE WHEN LENGTH(TRIM({value})) <= 10 "
        f"THEN CAST(NEW.{column} AS INTEGER) * 1000 ELSE CAST(NEW.{column} AS INTEGER) END "
        f"ELSE COALESCE(CAST(ROUND((julianday(NEW.{column}) - 2440587.5) * 86400000) AS INTEGER), NEW.{column}) END"
    )


def ensure_timestamp_triggers(connection: Connection) -> None:
    """Idempotently install SQLite timestamp normalization triggers.

    The database bootstrap owns this adapter. SQLite does not expose trigger
    creation through SQLAlchemy's schema API, so the final DDL remains a narrow
    dialect-specific exception. Remove it after every non-legacy timestamp
    writer uses typed SQLAlchemy expressions.
    """

    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote_identifier
    for table in inspector.get_table_names():
        columns = _timestamp_columns(connection, table)
        if not columns:
            continue
        quoted_table = quote(table)
        quoted_columns = [quote(column) for column in columns]
        insert_trigger = quote(f"normalize_{table}_timestamps_insert")
        update_trigger = quote(f"normalize_{table}_timestamps_update")
        assignments = ", ".join(
            f"{column} = {_timestamp_trigger_expression(column)}" for column in quoted_columns
        )
        column_list = ", ".join(quoted_columns)
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {insert_trigger}")
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {update_trigger}")
        connection.exec_driver_sql(
            f"CREATE TRIGGER {insert_trigger} AFTER INSERT ON {quoted_table} "
            f"BEGIN UPDATE {quoted_table} SET {assignments} WHERE rowid = NEW.rowid; END"
        )
        connection.exec_driver_sql(
            f"CREATE TRIGGER {update_trigger} AFTER UPDATE OF {column_list} ON {quoted_table} "
            f"BEGIN UPDATE {quoted_table} SET {assignments} WHERE rowid = NEW.rowid; END"
        )
