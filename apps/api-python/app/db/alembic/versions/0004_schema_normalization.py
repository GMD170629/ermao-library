"""Normalize every supported v14/0003 database to one physical schema.

Revision ID: 0004_schema_normalization
Revises: 0003_import_work_queue
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

from app.core.time import TimestampMilliseconds

revision: str = "0004_schema_normalization"
down_revision: str | Sequence[str] | None = "0003_import_work_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / "schema_snapshots" / "0004_baseline.json"
)
SchemaColumnType = (
    TimestampMilliseconds
    | sa.Boolean
    | sa.Float[float]
    | sa.Integer
    | sa.JSON
    | sa.Text
    | sa.String
)


def _load_snapshot() -> dict[str, object]:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("revision") != down_revision:
        raise RuntimeError("0004 schema snapshot is invalid")
    return payload


def _type_from_token(token: str) -> SchemaColumnType:
    scalar_types: dict[str, SchemaColumnType] = {
        "BIGINT": TimestampMilliseconds(),
        "BOOLEAN": sa.Boolean(),
        "FLOAT": sa.Float(),
        "INTEGER": sa.Integer(),
        "JSON": sa.JSON(),
        "TEXT": sa.Text(),
    }
    if token in scalar_types:
        return scalar_types[token]
    if token.startswith("VARCHAR(") and token.endswith(")"):
        return sa.String(length=int(token[8:-1]))
    raise RuntimeError(f"unsupported 0004 schema type: {token}")


def _server_default(value: object) -> sa.ColumnElement[object] | str | None:
    if value is None:
        return None
    if value == "unixepoch() * 1000":
        return sa.func.unixepoch() * 1000
    if (
        isinstance(value, str)
        and len(value) >= 2
        and value.startswith("'")
        and value.endswith("'")
    ):
        return value[1:-1]
    raise RuntimeError(f"unsupported 0004 schema default: {value!r}")


def _check_constraint(name: str) -> sa.CheckConstraint:
    if name == "ShelfCollectionMembership_distinct_shelves_check":
        expression = sa.column("collectionId") != sa.column("shelfId")
    elif name == "ImportWorkItem_target_check":
        kind: sa.ColumnClause[object] = sa.column("kind")
        scan_job_id: sa.ColumnClause[object] = sa.column("scanJobId")
        import_task_id: sa.ColumnClause[object] = sa.column("importTaskId")
        expression = sa.or_(
            sa.and_(
                kind == "SCAN_DIRECTORY",
                scan_job_id.is_not(None),
                import_task_id.is_(None),
            ),
            sa.and_(
                kind == "IMPORT_SOURCE",
                import_task_id.is_not(None),
                scan_job_id.is_(None),
            ),
        )
    else:
        raise RuntimeError(f"unsupported 0004 check constraint: {name}")
    return sa.CheckConstraint(expression, name=name)


def _index_predicate(table: sa.Table, token: object) -> sa.ColumnElement[bool] | None:
    if token is None:
        return None
    if token == "active_kindle_delivery":
        return table.c.status.in_(("queued", "sending"))
    if token == "primary_visible_edition":
        return sa.and_(table.c.primary == 1, table.c.hidden == 0)
    if token == "unresolved_organize_job":
        return table.c.status.in_(
            (
                "LOOKUP_PENDING",
                "PENDING",
                "QUEUED",
                "RUNNING",
                "RETRY_WAIT",
                "REVIEWING",
                "FAILED",
            )
        )
    raise RuntimeError(f"unsupported 0004 index predicate: {token!r}")


def _list_value(mapping: Mapping[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise TypeError(f"0004 schema snapshot field {key!r} must be a list")
    return value


def _schema_tables(
    snapshot: Mapping[str, object],
) -> tuple[sa.MetaData, list[sa.Table]]:
    metadata = sa.MetaData()
    table_specs = _list_value(snapshot, "tables")

    tables: list[sa.Table] = []
    for untyped_spec in table_specs:
        if not isinstance(untyped_spec, dict):
            raise TypeError("0004 schema snapshot contains an invalid table")
        spec: dict[str, object] = untyped_spec
        table_name = str(spec["name"])
        column_specs = _list_value(spec, "columns")
        columns: list[sa.Column] = []
        for untyped_column in column_specs:
            if not isinstance(untyped_column, dict):
                raise TypeError(f"invalid 0004 column in {table_name}")
            column: dict[str, object] = untyped_column
            columns.append(
                sa.Column(
                    str(column["name"]),
                    _type_from_token(str(column["type"])),
                    nullable=bool(column["nullable"]),
                    server_default=_server_default(column.get("default")),
                )
            )

        constraints: list[sa.Constraint] = []
        primary_key = spec.get("primary_key")
        if not isinstance(primary_key, dict):
            raise TypeError(f"0004 schema snapshot has no primary key for {table_name}")
        primary_columns = primary_key.get("columns")
        if isinstance(primary_columns, list) and primary_columns:
            constraints.append(
                sa.PrimaryKeyConstraint(
                    *(str(value) for value in primary_columns),
                    name=(
                        str(primary_key["name"])
                        if primary_key.get("name") is not None
                        else None
                    ),
                )
            )

        for untyped_unique in _list_value(spec, "unique_constraints"):
            if not isinstance(untyped_unique, dict):
                raise TypeError(f"invalid 0004 unique constraint in {table_name}")
            unique: dict[str, object] = untyped_unique
            unique_columns = unique.get("columns")
            if not isinstance(unique_columns, list):
                raise TypeError(f"invalid 0004 unique columns in {table_name}")
            constraints.append(
                sa.UniqueConstraint(
                    *(str(value) for value in unique_columns),
                    name=(
                        str(unique["name"]) if unique.get("name") is not None else None
                    ),
                )
            )

        for untyped_foreign_key in _list_value(spec, "foreign_keys"):
            if not isinstance(untyped_foreign_key, dict):
                raise TypeError(f"invalid 0004 foreign key in {table_name}")
            foreign_key: dict[str, object] = untyped_foreign_key
            local_columns = foreign_key.get("columns")
            remote_columns = foreign_key.get("referred_columns")
            options = foreign_key.get("options")
            if not isinstance(local_columns, list) or not isinstance(
                remote_columns, list
            ):
                raise TypeError(f"invalid 0004 foreign key columns in {table_name}")
            if not isinstance(options, dict):
                raise TypeError(f"invalid 0004 foreign key options in {table_name}")
            referred_table = str(foreign_key["referred_table"])
            constraints.append(
                sa.ForeignKeyConstraint(
                    [str(value) for value in local_columns],
                    [f"{referred_table}.{value}" for value in remote_columns],
                    name=(
                        str(foreign_key["name"])
                        if foreign_key.get("name") is not None
                        else None
                    ),
                    ondelete=(
                        str(options["ondelete"])
                        if options.get("ondelete") is not None
                        else None
                    ),
                    onupdate=(
                        str(options["onupdate"])
                        if options.get("onupdate") is not None
                        else None
                    ),
                )
            )

        for untyped_check in _list_value(spec, "checks"):
            if not isinstance(untyped_check, dict) or not untyped_check.get("name"):
                raise TypeError(f"invalid 0004 check constraint in {table_name}")
            constraints.append(_check_constraint(str(untyped_check["name"])))

        table = sa.Table(table_name, metadata, *columns, *constraints)
        for untyped_index in _list_value(spec, "indexes"):
            if not isinstance(untyped_index, dict):
                raise TypeError(f"invalid 0004 index in {table_name}")
            index: dict[str, object] = untyped_index
            index_columns = index.get("columns")
            if not isinstance(index_columns, list):
                raise TypeError(f"invalid 0004 index columns in {table_name}")
            sa.Index(
                str(index["name"]),
                *(table.c[str(value)] for value in index_columns),
                unique=bool(index["unique"]),
                sqlite_where=_index_predicate(table, index.get("predicate")),
            )
        tables.append(table)
    return metadata, tables


def _validate_source_schema(connection: Connection, tables: Sequence[sa.Table]) -> None:
    inspector = sa.inspect(connection)
    expected_names = {table.name for table in tables}
    actual_names = set(inspector.get_table_names()) - {"alembic_version"}
    if actual_names != expected_names:
        raise RuntimeError(
            "0004 requires an intact v14/0003 database; "
            f"table difference={sorted(actual_names ^ expected_names)!r}"
        )
    for table in tables:
        expected_columns = {column.name for column in table.columns}
        actual_columns = {
            str(column["name"]) for column in inspector.get_columns(table.name)
        }
        if actual_columns != expected_columns:
            raise RuntimeError(
                "0004 requires an intact v14/0003 database; "
                f"{table.name} column difference="
                f"{sorted(actual_columns ^ expected_columns)!r}"
            )


def _normalize_timestamp_values(connection: Connection, table: sa.Table) -> None:
    timestamp_columns = [
        column
        for column in table.columns
        if isinstance(column.type, TimestampMilliseconds)
    ]
    for column in timestamp_columns:
        text_value = sa.cast(column, sa.Text())
        converted = sa.case(
            (
                sa.func.instr(text_value, "-") > 0,
                sa.cast(sa.func.strftime("%s", text_value), sa.BigInteger()) * 1000,
            ),
            else_=sa.cast(text_value, sa.BigInteger()),
        )
        connection.execute(
            sa.update(table)
            .where(column.is_not(None), sa.func.typeof(column) == "text")
            .values({column.name: converted})
        )


def upgrade() -> None:
    snapshot = _load_snapshot()
    _metadata, tables = _schema_tables(snapshot)
    connection = op.get_bind()
    _validate_source_schema(connection, tables)

    for table in tables:
        with op.batch_alter_table(
            table.name,
            recreate="always",
            copy_from=table,
        ):
            pass
        _normalize_timestamp_values(connection, table)


def downgrade() -> None:
    raise RuntimeError(
        "0004_schema_normalization is intentionally irreversible; "
        "restore the pre-migration SQLite snapshot"
    )
