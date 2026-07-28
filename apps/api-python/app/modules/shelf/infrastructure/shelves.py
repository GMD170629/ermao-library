"""SQLAlchemy persistence for personal shelves and shelf-work links."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    AuthorizationContext,
    monitor_folder_visibility_predicate,
)
from app.models.library import LibraryEdition, LibraryWork
from app.models.settings import MonitorFolder
from app.models.shelf import Shelf, ShelfWork


def _entity_record(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key)
        for prop in mapper.column_attrs
    }


def list_shelves_for_user(db: Session, user_id: str) -> list[dict[str, Any]]:
    if not sa_inspect(db.get_bind()).has_table(Shelf.__tablename__):
        return []
    rows = db.scalars(
        select(Shelf)
        .where(Shelf.owner_user_id == user_id)
        .order_by(
            func.coalesce(Shelf.pinned, False).desc(),
            Shelf.updated_at.desc(),
        )
    ).all()
    return [_entity_record(row) for row in rows]


def get_owned_shelf(
    db: Session,
    shelf_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    if not sa_inspect(db.get_bind()).has_table(Shelf.__tablename__):
        return None
    row = db.scalar(
        select(Shelf).where(
            Shelf.id == shelf_id,
            Shelf.owner_user_id == user_id,
        )
    )
    return _entity_record(row) if row else None


def shelf_exists(db: Session, shelf_id: str) -> bool:
    return db.scalar(select(Shelf.id).where(Shelf.id == shelf_id)) is not None


def list_static_shelf_work_ids(db: Session, shelf_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ShelfWork.work_id)
            .where(ShelfWork.shelf_id == shelf_id)
            .order_by(ShelfWork.created_at.asc())
        ).all()
    )


def filter_visible_work_ids(
    db: Session,
    work_ids: list[str],
    context: AuthorizationContext,
) -> list[str]:
    if not work_ids:
        return []
    visible: set[str] = set()
    for chunk_start in range(0, len(work_ids), 400):
        chunk = work_ids[chunk_start : chunk_start + 400]
        stmt = select(LibraryWork.id).where(LibraryWork.id.in_(chunk))
        if not context.is_admin:
            accessible_edition = aliased(LibraryEdition)
            any_visible_edition = aliased(LibraryEdition)
            has_accessible = exists(
                select(accessible_edition.id).where(
                    accessible_edition.work_id == LibraryWork.id,
                    accessible_edition.hidden.is_(False),
                    monitor_folder_visibility_predicate(
                        context,
                        accessible_edition.monitor_folder_id,
                    ),
                )
            )
            has_any = exists(
                select(any_visible_edition.id).where(
                    any_visible_edition.work_id == LibraryWork.id,
                    any_visible_edition.hidden.is_(False),
                )
            )
            stmt = stmt.where(
                or_(
                    has_accessible,
                    and_(
                        ~has_any,
                        monitor_folder_visibility_predicate(
                            context,
                            LibraryWork.monitor_folder_id,
                        ),
                    ),
                )
            )
        visible.update(str(row) for row in db.scalars(stmt).all())
    return [
        str(work_id)
        for work_id in work_ids
        if str(work_id) in visible
    ]


def list_work_cards(
    db: Session,
    work_ids: list[str],
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.execute(
        select(
            LibraryWork.id,
            LibraryWork.title,
            LibraryWork.author,
        ).where(LibraryWork.id.in_(work_ids))
    ).mappings().all()
    by_id = {
        str(row["id"]): {
            "id": row["id"],
            "title": row["title"],
            "author": row["author"],
        }
        for row in rows
    }
    return [
        by_id[str(work_id)]
        for work_id in work_ids
        if str(work_id) in by_id
    ]


def create_shelf(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    shelf = Shelf(
        id=str(values["id"]),
        owner_user_id=str(values["ownerUserId"]),
        name=str(values["name"]),
        description=values.get("description"),
        kind=str(values["kind"]),
        rules_json=str(values["rulesJson"]),
        pinned=bool(values["pinned"]),
        created_at=values["createdAt"],
        updated_at=values["updatedAt"],
    )
    db.add(shelf)
    db.flush()
    return _entity_record(shelf)


def update_shelf(
    db: Session,
    shelf_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    shelf = db.get(Shelf, shelf_id)
    if shelf is None:
        return None
    field_map = {
        "name": "name",
        "description": "description",
        "pinned": "pinned",
        "kind": "kind",
        "rulesJson": "rules_json",
        "updatedAt": "updated_at",
    }
    for external_name, attribute_name in field_map.items():
        if external_name in values:
            setattr(shelf, attribute_name, values[external_name])
    db.flush()
    return _entity_record(shelf)


def replace_shelf_works(
    db: Session,
    shelf_id: str,
    work_ids: list[str],
    *,
    now: datetime,
) -> None:
    db.execute(delete(ShelfWork).where(ShelfWork.shelf_id == shelf_id))
    db.add_all(
        [
            ShelfWork(
                shelf_id=shelf_id,
                work_id=work_id,
                created_at=now,
            )
            for work_id in work_ids
        ]
    )
    db.flush()


def add_shelf_work(
    db: Session,
    *,
    shelf_id: str,
    work_id: str,
    now: datetime,
) -> None:
    if db.get(ShelfWork, (shelf_id, work_id)) is not None:
        return
    db.add(
        ShelfWork(
            shelf_id=shelf_id,
            work_id=work_id,
            created_at=now,
        )
    )
    db.flush()


def remove_shelf_work(
    db: Session,
    *,
    shelf_id: str,
    work_id: str,
) -> None:
    db.execute(
        delete(ShelfWork).where(
            ShelfWork.shelf_id == shelf_id,
            ShelfWork.work_id == work_id,
        )
    )


def delete_shelf(db: Session, shelf_id: str) -> bool:
    db.execute(delete(ShelfWork).where(ShelfWork.shelf_id == shelf_id))
    result = db.execute(delete(Shelf).where(Shelf.id == shelf_id))
    db.flush()
    return bool(result.rowcount)


def clear_monitor_folder_shelf_links(
    db: Session,
    shelf_id: str,
    *,
    now: datetime,
) -> None:
    db.execute(
        update(MonitorFolder)
        .where(MonitorFolder.shelf_id == shelf_id)
        .values(shelf_id=None, updated_at=now)
    )
