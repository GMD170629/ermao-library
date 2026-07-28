"""ORM helpers for Source / SourceSearchRecord HTTP adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from app.models.import_pipeline import Source, SourceSearchRecord
from app.modules.imports.infrastructure.legacy_persistence import (
    get_entity,
    legacy_delete_by_id,
    legacy_get_by_id,
    legacy_insert,
    legacy_update,
    list_entities,
)
from app.modules.imports.infrastructure.schema import has_table, table_columns


def list_sources(db: Session) -> list[dict[str, Any]]:
    if not has_table(db, "Source"):
        return []
    return list_entities(
        db,
        "Source",
        order_by=(Source.priority.asc(), Source.created_at.desc()),
    )


def get_source(db: Session, source_id: str) -> dict[str, Any] | None:
    return legacy_get_by_id(db, "Source", source_id)


def create_source(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    return legacy_insert(db, "Source", values)


def update_source(db: Session, source_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    legacy_update(db, "Source", source_id, values)
    return legacy_get_by_id(db, "Source", source_id)


def delete_source(db: Session, source_id: str) -> bool:
    if legacy_get_by_id(db, "Source", source_id) is None:
        return False
    legacy_delete_by_id(db, "Source", source_id)
    return True


def list_source_search_records_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    source_id: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if not has_table(db, "SourceSearchRecord"):
        return [], 0
    filters: list[Any] = []
    if source_id:
        filters.append(SourceSearchRecord.source_id == source_id)
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status != "all":
        filters.append(SourceSearchRecord.status == normalized_status)
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        filters.append(
            or_(
                SourceSearchRecord.title.like(pattern),
                func.coalesce(SourceSearchRecord.author, "").like(pattern),
            )
        )
    total = int(
        db.scalar(select(func.count()).select_from(SourceSearchRecord).where(*filters)) or 0
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    column_attrs = [
        prop
        for prop in sa_inspect(SourceSearchRecord).mapper.column_attrs
        if prop.columns[0].name in table_columns(db, "SourceSearchRecord")
    ]
    columns = [getattr(SourceSearchRecord, prop.key) for prop in column_attrs]
    stmt = select(*columns)
    if filters:
        stmt = stmt.where(*filters)
    rows = db.execute(
        stmt.order_by(SourceSearchRecord.created_at.desc(), SourceSearchRecord.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    records = [
        {column_attrs[index].columns[0].name: value for index, value in enumerate(row)}
        for row in rows
    ]
    return records, total


def get_source_search_record(db: Session, record_id: str) -> dict[str, Any] | None:
    return legacy_get_by_id(db, "SourceSearchRecord", record_id)


def create_source_search_record(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    return legacy_insert(db, "SourceSearchRecord", values)


def update_source_search_record(
    db: Session, record_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    legacy_update(db, "SourceSearchRecord", record_id, values)
    return legacy_get_by_id(db, "SourceSearchRecord", record_id)


def delete_source_search_record(db: Session, record_id: str) -> bool:
    if legacy_get_by_id(db, "SourceSearchRecord", record_id) is None:
        return False
    legacy_delete_by_id(db, "SourceSearchRecord", record_id)
    return True


def find_source_search_record(
    db: Session, *, source_id: str, external_id: str
) -> dict[str, Any] | None:
    return get_entity(
        db,
        "SourceSearchRecord",
        SourceSearchRecord.source_id == source_id,
        SourceSearchRecord.external_id == external_id,
    )
