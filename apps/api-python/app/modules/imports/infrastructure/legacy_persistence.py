"""Generic ORM persistence helpers matching legacy camelCase row dicts."""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import delete, func, inspect as sa_inspect, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.imports.infrastructure.schema import (
    entity_as_legacy_dict,
    model_for_table,
    reflected_table,
    table_columns,
)


def _existing_column_attrs(db: Session, model: type) -> list[Any]:
    existing = table_columns(db, model.__tablename__)
    return [
        prop
        for prop in sa_inspect(model).mapper.column_attrs
        if prop.columns[0].name in existing
    ]


def _legacy_dict_from_row(column_attrs: list[Any], row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        column_attrs[index].columns[0].name: value
        for index, value in enumerate(row)
    }


def legacy_insert(db: Session, table: str, values: dict[str, Any]) -> dict[str, Any]:
    model = model_for_table(table)
    if model is None:
        raise ValueError(f"Unsupported table for legacy insert: {table}")
    columns = table_columns(db, table)
    filtered = {key: value for key, value in values.items() if key in columns}
    db.execute(insert(reflected_table(db, table)).values(filtered))
    db.flush()
    row_id = str(filtered["id"])
    return legacy_get_by_id(db, table, row_id) or filtered


def legacy_update(db: Session, table: str, row_id: str, values: dict[str, Any]) -> None:
    model = model_for_table(table)
    if model is None:
        raise ValueError(f"Unsupported table for legacy update: {table}")
    columns = table_columns(db, table)
    filtered = {key: value for key, value in values.items() if key in columns}
    if not filtered:
        return
    table_obj = reflected_table(db, table)
    db.execute(update(table_obj).where(table_obj.c.id == row_id).values(filtered))


def legacy_get_by_id(db: Session, table: str, row_id: str) -> dict[str, Any] | None:
    model = model_for_table(table)
    if model is None:
        return None
    column_attrs = _existing_column_attrs(db, model)
    if not column_attrs:
        return None
    columns = [getattr(model, prop.key) for prop in column_attrs]
    row = db.execute(select(*columns).where(model.id == row_id)).first()
    return _legacy_dict_from_row(column_attrs, row) if row is not None else None


def legacy_delete_by_id(db: Session, table: str, row_id: str) -> None:
    model = model_for_table(table)
    if model is None:
        return
    db.execute(delete(model).where(model.id == row_id))


def list_entities(
    db: Session,
    table: str,
    *filters: ColumnElement[bool],
    order_by: Sequence[ColumnElement[Any]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    model = model_for_table(table)
    if model is None:
        return []
    column_attrs = _existing_column_attrs(db, model)
    if not column_attrs:
        return []
    columns = [getattr(model, prop.key) for prop in column_attrs]
    stmt = select(*columns)
    if filters:
        stmt = stmt.where(*filters)
    if order_by:
        stmt = stmt.order_by(*order_by)
    if limit is not None:
        stmt = stmt.limit(limit)
    return [_legacy_dict_from_row(column_attrs, row) for row in db.execute(stmt).all()]


def get_entity(
    db: Session,
    table: str,
    *filters: ColumnElement[bool],
    order_by: Sequence[ColumnElement[Any]] | None = None,
) -> dict[str, Any] | None:
    rows = list_entities(db, table, *filters, order_by=order_by, limit=1)
    return rows[0] if rows else None


def count_entities(db: Session, table: str, *filters: ColumnElement[bool]) -> int:
    model = model_for_table(table)
    if model is None:
        return 0
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(*filters)
    return int(db.scalar(stmt) or 0)


def scalar_select(db: Session, statement: Any, default: Any = None) -> Any:
    value = db.scalar(statement)
    return default if value is None else value
