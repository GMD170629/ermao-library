"""SQLAlchemy persistence for personal shelves and book links."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
)
from app.core.sql_batches import sqlite_parameter_chunks
from app.models import LibraryBook, LibraryBookMetadata
from app.models.shelf import Shelf, ShelfBook
from app.modules.shelf.infrastructure.models import ShelfCollectionMembership


def _entity_record(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
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
            Shelf.id.asc(),
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


def shelf_accepts_books(db: Session, shelf_id: str) -> bool:
    kind = db.scalar(select(Shelf.kind).where(Shelf.id == shelf_id))
    return str(kind or "").upper() == "STATIC"


def list_collection_ids_by_shelf_ids(
    db: Session,
    shelf_ids: list[str],
) -> dict[str, list[str]]:
    result = {shelf_id: [] for shelf_id in shelf_ids}
    if not shelf_ids:
        return result
    rows = db.execute(
        select(
            ShelfCollectionMembership.shelf_id,
            ShelfCollectionMembership.collection_id,
        )
        .where(ShelfCollectionMembership.shelf_id.in_(shelf_ids))
        .order_by(
            ShelfCollectionMembership.created_at.asc(),
            ShelfCollectionMembership.collection_id.asc(),
        )
    ).all()
    for shelf_id, collection_id in rows:
        result.setdefault(str(shelf_id), []).append(str(collection_id))
    return result


def collection_member_counts(
    db: Session,
    collection_ids: list[str],
) -> dict[str, int]:
    result = {collection_id: 0 for collection_id in collection_ids}
    if not collection_ids:
        return result
    rows = db.execute(
        select(
            ShelfCollectionMembership.collection_id,
            func.count(ShelfCollectionMembership.shelf_id),
        )
        .where(ShelfCollectionMembership.collection_id.in_(collection_ids))
        .group_by(ShelfCollectionMembership.collection_id)
    ).all()
    for collection_id, count in rows:
        result[str(collection_id)] = int(count)
    return result


def list_member_shelf_ids(db: Session, collection_id: str) -> list[str]:
    return [
        str(shelf_id)
        for shelf_id in db.scalars(
            select(ShelfCollectionMembership.shelf_id)
            .where(ShelfCollectionMembership.collection_id == collection_id)
            .order_by(
                ShelfCollectionMembership.created_at.asc(),
                ShelfCollectionMembership.shelf_id.asc(),
            )
        ).all()
    ]


def list_owned_shelves_by_ids(
    db: Session,
    shelf_ids: list[str],
    user_id: str,
) -> list[dict[str, Any]]:
    if not shelf_ids:
        return []
    rows = db.scalars(
        select(Shelf).where(
            Shelf.id.in_(shelf_ids),
            Shelf.owner_user_id == user_id,
        )
    ).all()
    by_id = {row.id: _entity_record(row) for row in rows}
    return [by_id[shelf_id] for shelf_id in shelf_ids if shelf_id in by_id]


def replace_collection_members(
    db: Session,
    *,
    collection_id: str,
    shelf_ids: list[str],
    now: datetime,
) -> None:
    rows = [
        {
            "collection_id": collection_id,
            "shelf_id": shelf_id,
            "created_at": now,
        }
        for shelf_id in shelf_ids
    ]
    db.execute(
        delete(ShelfCollectionMembership).where(
            ShelfCollectionMembership.collection_id == collection_id
        )
    )
    for chunk in sqlite_parameter_chunks(rows, parameters_per_row=3):
        db.execute(sqlite_insert(ShelfCollectionMembership).values(list(chunk)))


def replace_shelf_collections(
    db: Session,
    *,
    shelf_id: str,
    collection_ids: list[str],
    now: datetime,
) -> None:
    rows = [
        {
            "collection_id": collection_id,
            "shelf_id": shelf_id,
            "created_at": now,
        }
        for collection_id in collection_ids
    ]
    db.execute(
        delete(ShelfCollectionMembership).where(
            ShelfCollectionMembership.shelf_id == shelf_id
        )
    )
    for chunk in sqlite_parameter_chunks(rows, parameters_per_row=3):
        db.execute(sqlite_insert(ShelfCollectionMembership).values(list(chunk)))


def touch_shelves_updated_at(
    db: Session,
    shelf_ids: list[str],
    *,
    now: datetime,
) -> None:
    if not shelf_ids:
        return
    db.execute(update(Shelf).where(Shelf.id.in_(shelf_ids)).values(updated_at=now))


def collection_has_members(db: Session, collection_id: str) -> bool:
    return (
        db.scalar(
            select(ShelfCollectionMembership.collection_id)
            .where(ShelfCollectionMembership.collection_id == collection_id)
            .limit(1)
        )
        is not None
    )


def list_static_shelf_book_ids(db: Session, shelf_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ShelfBook.book_id)
            .where(ShelfBook.shelf_id == shelf_id)
            .order_by(ShelfBook.created_at.asc())
        ).all()
    )


def list_static_shelf_book_page(
    db: Session,
    shelf_id: str,
    context: AuthorizationContext,
    *,
    page: int,
    page_size: int,
) -> tuple[list[str], int]:
    predicates = [ShelfBook.shelf_id == shelf_id]
    if not context.is_admin:
        predicates.append(book_visibility_predicate(context))
    total = int(
        db.scalar(
            select(func.count())
            .select_from(ShelfBook)
            .join(LibraryBook, LibraryBook.id == ShelfBook.book_id)
            .where(*predicates)
        )
        or 0
    )
    book_ids = list(
        db.scalars(
            select(ShelfBook.book_id)
            .join(LibraryBook, LibraryBook.id == ShelfBook.book_id)
            .where(*predicates)
            .order_by(ShelfBook.created_at.asc(), ShelfBook.book_id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()
    )
    return [str(book_id) for book_id in book_ids], total


def filter_visible_book_ids(
    db: Session,
    book_ids: list[str],
    context: AuthorizationContext,
) -> list[str]:
    if not book_ids:
        return []
    visible: set[str] = set()
    for chunk_start in range(0, len(book_ids), 400):
        chunk = book_ids[chunk_start : chunk_start + 400]
        stmt = select(LibraryBook.id).where(LibraryBook.id.in_(chunk))
        if not context.is_admin:
            stmt = stmt.where(book_visibility_predicate(context))
        visible.update(str(row) for row in db.scalars(stmt).all())
    return [str(book_id) for book_id in book_ids if str(book_id) in visible]


def list_book_cards(
    db: Session,
    book_ids: list[str],
) -> list[dict[str, Any]]:
    if not book_ids:
        return []
    rows = (
        db.execute(
            select(
                LibraryBook.id,
                LibraryBookMetadata.title,
                LibraryBookMetadata.author,
            )
            .select_from(LibraryBook)
            .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
            .where(LibraryBook.id.in_(book_ids))
        )
        .mappings()
        .all()
    )
    by_id = {
        str(row["id"]): {
            "id": row["id"],
            "title": row["title"],
            "author": row["author"],
        }
        for row in rows
    }
    return [by_id[str(book_id)] for book_id in book_ids if str(book_id) in by_id]


def create_shelf(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    shelf = db.execute(
        sqlite_insert(Shelf)
        .values(
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
        .returning(Shelf)
    ).scalar_one()
    return _entity_record(shelf)


def update_shelf(
    db: Session,
    shelf_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    field_map = {
        "name": "name",
        "description": "description",
        "pinned": "pinned",
        "kind": "kind",
        "rulesJson": "rules_json",
        "updatedAt": "updated_at",
    }
    patch = {
        attribute_name: values[external_name]
        for external_name, attribute_name in field_map.items()
        if external_name in values
    }
    shelf = db.execute(
        update(Shelf).where(Shelf.id == shelf_id).values(**patch).returning(Shelf)
    ).scalar_one_or_none()
    if shelf is None:
        return None
    return _entity_record(shelf)


def replace_shelf_books(
    db: Session,
    shelf_id: str,
    book_ids: list[str],
    *,
    now: datetime,
) -> None:
    rows = [
        {"shelf_id": shelf_id, "book_id": book_id, "created_at": now}
        for book_id in book_ids
    ]
    db.execute(delete(ShelfBook).where(ShelfBook.shelf_id == shelf_id))
    for chunk in sqlite_parameter_chunks(rows, parameters_per_row=3):
        db.execute(sqlite_insert(ShelfBook).values(list(chunk)))


def add_shelf_book(
    db: Session,
    *,
    shelf_id: str,
    book_id: str,
    now: datetime,
) -> None:
    if not shelf_accepts_books(db, shelf_id):
        raise ValueError("COLLECTION_CANNOT_CONTAIN_BOOKS")
    db.execute(
        sqlite_insert(ShelfBook)
        .values(shelf_id=shelf_id, book_id=book_id, created_at=now)
        .on_conflict_do_nothing(index_elements=[ShelfBook.shelf_id, ShelfBook.book_id])
    )


def add_shelf_books(
    db: Session,
    *,
    shelf_id: str,
    book_ids: tuple[str, ...],
    now: datetime,
) -> None:
    rows = tuple(
        {"shelf_id": shelf_id, "book_id": book_id, "created_at": now}
        for book_id in book_ids
    )
    for chunk in sqlite_parameter_chunks(rows, parameters_per_row=3):
        db.execute(
            sqlite_insert(ShelfBook)
            .values(list(chunk))
            .on_conflict_do_nothing(
                index_elements=[ShelfBook.shelf_id, ShelfBook.book_id]
            )
        )


def remove_shelf_book(
    db: Session,
    *,
    shelf_id: str,
    book_id: str,
) -> None:
    db.execute(
        delete(ShelfBook).where(
            ShelfBook.shelf_id == shelf_id,
            ShelfBook.book_id == book_id,
        )
    )


def remove_shelf_books(
    db: Session,
    *,
    shelf_id: str,
    book_ids: tuple[str, ...],
) -> None:
    for chunk in sqlite_parameter_chunks(book_ids, parameters_per_row=1):
        db.execute(
            delete(ShelfBook).where(
                ShelfBook.shelf_id == shelf_id,
                ShelfBook.book_id.in_(chunk),
            )
        )


def delete_shelf(db: Session, shelf_id: str) -> bool:
    db.execute(
        delete(ShelfCollectionMembership).where(
            or_(
                ShelfCollectionMembership.collection_id == shelf_id,
                ShelfCollectionMembership.shelf_id == shelf_id,
            )
        )
    )
    db.execute(delete(ShelfBook).where(ShelfBook.shelf_id == shelf_id))
    result = db.execute(delete(Shelf).where(Shelf.id == shelf_id))
    return bool(result.rowcount)


def clear_library_shelf_links(
    db: Session,
    shelf_id: str,
    *,
    now: datetime,
) -> None:
    del db, shelf_id, now
