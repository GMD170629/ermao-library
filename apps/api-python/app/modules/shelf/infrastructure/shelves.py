"""ORM persistence for personal shelves and shelf-work links."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Table, delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.modules.imports.infrastructure.schema import has_table, reflected_table


def _has_table(db: Session, table: str) -> bool:
    return has_table(db, table)


def _has_column(db: Session, table: str, column: str) -> bool:
    if not _has_table(db, table):
        return False
    from app.modules.imports.infrastructure.schema import table_columns

    return column in table_columns(db, table)


def _legacy_table(db: Session, table: str) -> Table | None:
    if not _has_table(db, table):
        return None
    return reflected_table(db, table)


def list_shelves_for_user(db: Session, user_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "Shelf")
    if table is None:
        return []
    stmt = select(table)
    if "ownerUserId" in table.c:
        stmt = stmt.where(table.c.ownerUserId == user_id)
    order_by = [table.c.updatedAt.desc()]
    if "pinned" in table.c:
        order_by = [func.coalesce(table.c.pinned, False).desc(), *order_by]
    rows = db.execute(stmt.order_by(*order_by)).mappings().all()
    return [dict(row) for row in rows]


def get_owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    table = _legacy_table(db, "Shelf")
    if table is None:
        return None
    filters = [table.c.id == shelf_id]
    if "ownerUserId" in table.c:
        filters.append(table.c.ownerUserId == user_id)
    row = db.execute(select(table).where(*filters)).mappings().first()
    return dict(row) if row else None


def shelf_exists(db: Session, shelf_id: str) -> bool:
    table = _legacy_table(db, "Shelf")
    if table is None:
        return False
    return db.scalar(select(table.c.id).where(table.c.id == shelf_id)) is not None


def list_static_shelf_work_ids(db: Session, shelf_id: str) -> list[str]:
    table = _legacy_table(db, "ShelfWork")
    if table is None:
        return []
    rows = db.execute(
        select(table.c.workId).where(table.c.shelfId == shelf_id).order_by(table.c.createdAt.asc())
    ).all()
    return [str(row.workId) for row in rows]


def filter_visible_work_ids(
    db: Session,
    work_ids: list[str],
    context: AuthorizationContext,
) -> list[str]:
    if not work_ids:
        return []
    table = _legacy_table(db, "LibraryWork")
    if table is None:
        return []
    visible: set[str] = set()
    for chunk_start in range(0, len(work_ids), 400):
        chunk = work_ids[chunk_start : chunk_start + 400]
        stmt = select(table.c.id).where(table.c.id.in_(chunk))
        if not context.is_admin:
            # Prefer edition-scoped visibility when editions exist; fall back to origin folder.
            from app.core.authorization import monitor_folder_visibility_predicate
            from sqlalchemy import exists, or_, and_
            from sqlalchemy.orm import aliased
            from app.models.library import LibraryEdition

            accessible_edition = aliased(LibraryEdition)
            any_visible_edition = aliased(LibraryEdition)
            has_accessible = exists(
                select(accessible_edition.id).where(
                    accessible_edition.work_id == table.c.id,
                    accessible_edition.hidden.is_(False),
                    monitor_folder_visibility_predicate(
                        context, accessible_edition.monitor_folder_id
                    ),
                )
            )
            has_any = exists(
                select(any_visible_edition.id).where(
                    any_visible_edition.work_id == table.c.id,
                    any_visible_edition.hidden.is_(False),
                )
            )
            if "monitorFolderId" in table.c:
                stmt = stmt.where(
                    or_(
                        has_accessible,
                        and_(
                            ~has_any,
                            monitor_folder_visibility_predicate(context, table.c.monitorFolderId),
                        ),
                    )
                )
            else:
                stmt = stmt.where(or_(has_accessible, ~has_any))
        rows = db.execute(stmt).all()
        visible.update(str(row.id) for row in rows)
    return [str(work_id) for work_id in work_ids if str(work_id) in visible]


def list_work_cards(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryWork")
    if not work_ids or table is None:
        return []
    cols = [table.c.id]
    if "title" in table.c:
        cols.append(table.c.title)
    if "author" in table.c:
        cols.append(table.c.author)
    rows = db.execute(select(*cols).where(table.c.id.in_(work_ids))).mappings().all()
    by_id = {
        str(row["id"]): {
            "id": row["id"],
            "title": row.get("title"),
            "author": row.get("author"),
        }
        for row in rows
    }
    return [by_id[str(work_id)] for work_id in work_ids if str(work_id) in by_id]


def create_shelf(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    table = _legacy_table(db, "Shelf")
    if table is None:
        raise RuntimeError("Shelf table is not available")
    payload = {key: value for key, value in values.items() if key in table.c}
    db.execute(insert(table).values(**payload))
    db.flush()
    row = db.execute(select(table).where(table.c.id == payload["id"])).mappings().first()
    return dict(row) if row else payload


def update_shelf(db: Session, shelf_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    table = _legacy_table(db, "Shelf")
    if table is None:
        return None
    payload = {key: value for key, value in values.items() if key in table.c}
    if payload:
        db.execute(update(table).where(table.c.id == shelf_id).values(**payload))
        db.flush()
    row = db.execute(select(table).where(table.c.id == shelf_id)).mappings().first()
    return dict(row) if row else None


def replace_shelf_works(
    db: Session,
    shelf_id: str,
    work_ids: list[str],
    *,
    now: datetime,
    commit: bool = True,
) -> None:
    table = _legacy_table(db, "ShelfWork")
    if table is None:
        return
    db.execute(delete(table).where(table.c.shelfId == shelf_id))
    for work_id in work_ids:
        db.execute(
            insert(table).values(shelfId=shelf_id, workId=work_id, createdAt=now)
        )
    if commit:
        db.commit()


def add_shelf_work(db: Session, *, shelf_id: str, work_id: str, now: datetime) -> None:
    table = _legacy_table(db, "ShelfWork")
    if table is None:
        return
    existing = db.execute(
        select(table.c.shelfId).where(
            table.c.shelfId == shelf_id, table.c.workId == work_id
        )
    ).first()
    if existing:
        return
    db.execute(insert(table).values(shelfId=shelf_id, workId=work_id, createdAt=now))


def remove_shelf_work(db: Session, *, shelf_id: str, work_id: str) -> None:
    table = _legacy_table(db, "ShelfWork")
    if table is None:
        return
    db.execute(
        delete(table).where(table.c.shelfId == shelf_id, table.c.workId == work_id)
    )


def delete_shelf(db: Session, shelf_id: str) -> bool:
    works = _legacy_table(db, "ShelfWork")
    if works is not None:
        db.execute(delete(works).where(works.c.shelfId == shelf_id))
    table = _legacy_table(db, "Shelf")
    if table is None:
        return False
    result = db.execute(delete(table).where(table.c.id == shelf_id))
    db.commit()
    return bool(result.rowcount)


def clear_monitor_folder_shelf_links(db: Session, shelf_id: str, *, now: datetime) -> None:
    table = _legacy_table(db, "MonitorFolder")
    if table is None or "shelfId" not in table.c:
        return
    values: dict[str, Any] = {"shelfId": None}
    if "updatedAt" in table.c:
        values["updatedAt"] = now
    db.execute(update(table).where(table.c.shelfId == shelf_id).values(**values))
