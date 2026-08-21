"""ORM persistence for Book and ReadableResource facets."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from hashlib import sha1
from typing import Any

from sqlalchemy import case, delete, distinct, exists, func, or_, select, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import to_timestamp_ms
from app.models.common import db_timestamp
from app.models import (
    LibraryFacet,
    LibraryBook,
    LibraryBookFacet,
)
from app.modules.library.domain.facets import FACET_KINDS
from app.services.book_identity import UNKNOWN_AUTHOR, normalize_identity_part


def parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def normalized_name(value: Any) -> str:
    return normalize_identity_part(str(value or "").strip())


def unique_names(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = re.sub(r"\s+", " ", str(value or "")).strip()
        normalized = normalized_name(name)
        if not name or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(name)
    return result


def split_authors(value: Any) -> list[str]:
    text_value = str(value or "").strip()
    if not text_value or text_value == UNKNOWN_AUTHOR:
        return []
    return unique_names(
        re.split(r"\s*(?:,|，|;|；|、|/|&|\band\b)\s*", text_value, flags=re.IGNORECASE)
    )


def book_tags(value: Any) -> list[str]:
    parsed = parse_json(value, [])
    if isinstance(parsed, list):
        return unique_names(parsed)
    return unique_names(re.split(r"[,，;；\n]", str(value or "")))


def _facet_id(kind: str, normalized: str) -> str:
    digest = sha1(f"{kind}\0{normalized}".encode()).hexdigest()[:24]
    return f"facet_{digest}"


def ensure_facet(db: Session, kind: str, name: str) -> str:
    normalized = normalized_name(name)
    if kind not in FACET_KINDS or not normalized:
        raise ValueError("分类名称无效")
    facet_id = _facet_id(kind, normalized)
    now = db_timestamp()
    db.execute(
        sqlite_insert(LibraryFacet)
        .values(
            id=facet_id,
            kind=kind,
            name=name,
            normalized_name=normalized,
            aliases="[]",
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[LibraryFacet.kind, LibraryFacet.normalized_name]
        )
    )
    existing = db.execute(
        select(LibraryFacet.id).where(
            LibraryFacet.kind == kind,
            LibraryFacet.normalized_name == normalized,
        )
    ).scalar_one()
    return str(existing)


def _facet_search_clause(search: str) -> Any | None:
    term = search.strip()
    if not term:
        return None
    pattern = f"%{term.lower()}%"
    return or_(
        func.lower(LibraryFacet.name).like(pattern),
        func.lower(LibraryFacet.aliases).like(pattern),
    )


def _facet_public_dict(facet: LibraryFacet, book_count: int) -> dict[str, Any]:
    return {
        "id": facet.id,
        "kind": facet.kind,
        "name": facet.name,
        "normalizedName": facet.normalized_name,
        "aliases": parse_json(facet.aliases, []),
        "createdAt": to_timestamp_ms(facet.created_at),
        "updatedAt": to_timestamp_ms(facet.updated_at),
        "bookCount": int(book_count or 0),
    }


def sync_book_facets(db: Session, book_id: str) -> None:
    """Synchronize persisted facets for one Book after a library change."""

    sync_books_facets(db, (book_id,))


def sync_books_facets(db: Session, book_ids: Iterable[str]) -> None:
    """Synchronize facets for a prepared Book set with bounded collection SQL."""

    unique_book_ids = tuple(dict.fromkeys(book_id for book_id in book_ids if book_id))
    if not unique_book_ids:
        return

    books = db.execute(
        select(
            LibraryBook.id,
            LibraryBook.author,
            LibraryBook.tags,
            LibraryBook.series_name,
        ).where(LibraryBook.id.in_(unique_book_ids))
    ).all()
    if not books:
        return

    now = db_timestamp()
    prepared = tuple(
        (
            str(book.id),
            tuple(
                (kind, name, normalized_name(name), sort_order)
                for kind, names in (
                    ("AUTHOR", split_authors(book.author)),
                    ("TAG", book_tags(book.tags)),
                    ("SERIES", unique_names([book.series_name])),
                )
                for sort_order, name in enumerate(names)
            ),
        )
        for book in books
    )
    facets: dict[tuple[str, str], tuple[str, str]] = {}
    for _book_id, values in prepared:
        for kind, name, normalized, _sort_order in values:
            facets.setdefault((kind, normalized), (name, _facet_id(kind, normalized)))
    facet_rows = [
        {
            "id": facet_id,
            "kind": kind,
            "name": name,
            "normalized_name": normalized,
            "aliases": "[]",
            "created_at": now,
            "updated_at": now,
        }
        for (kind, normalized), (name, facet_id) in facets.items()
    ]
    for chunk in sqlite_parameter_chunks(facet_rows, parameters_per_row=7):
        db.execute(
            sqlite_insert(LibraryFacet)
            .values(list(chunk))
            .on_conflict_do_nothing(
                index_elements=[LibraryFacet.kind, LibraryFacet.normalized_name]
            )
        )

    facet_ids: dict[tuple[str, str], str] = {}
    facet_keys = tuple(facets)
    for chunk in sqlite_parameter_chunks(facet_keys, parameters_per_row=2):
        rows = db.execute(
            select(
                LibraryFacet.kind,
                LibraryFacet.normalized_name,
                LibraryFacet.id,
            ).where(tuple_(LibraryFacet.kind, LibraryFacet.normalized_name).in_(chunk))
        )
        facet_ids.update(
            {(str(row.kind), str(row.normalized_name)): str(row.id) for row in rows}
        )
    missing = set(facet_keys) - set(facet_ids)
    if missing:
        raise RuntimeError(f"facet mapping incomplete; missing_count={len(missing)}")

    links = [
        {
            "facet_id": facet_ids[(kind, normalized)],
            "book_id": book_id,
            "sort_order": sort_order,
            "created_at": now,
        }
        for book_id, values in prepared
        for kind, _name, normalized, sort_order in values
    ]
    persisted_book_ids = tuple(book_id for book_id, _values in prepared)
    db.execute(
        delete(LibraryBookFacet).where(LibraryBookFacet.book_id.in_(persisted_book_ids))
    )
    for chunk in sqlite_parameter_chunks(links, parameters_per_row=4):
        db.execute(
            sqlite_insert(LibraryBookFacet)
            .values(list(chunk))
            .on_conflict_do_nothing(
                index_elements=[LibraryBookFacet.facet_id, LibraryBookFacet.book_id]
            )
        )


def count_categories(db: Session, kind: str, search: str = "") -> int:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    statement = (
        select(func.count())
        .select_from(LibraryFacet)
        .where(LibraryFacet.kind == normalized_kind)
    )
    search_clause = _facet_search_clause(search)
    if search_clause is not None:
        statement = statement.where(search_clause)
    return int(db.execute(statement).scalar() or 0)


def list_categories(
    db: Session,
    kind: str,
    search: str = "",
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    if limit is not None and (limit <= 0 or offset < 0):
        raise ValueError("分页参数无效")

    book_count = func.count(
        distinct(
            case(
                (
                    func.coalesce(LibraryBook.hidden, 0) == 0,
                    LibraryBookFacet.book_id,
                ),
            )
        )
    ).label("bookCount")
    statement = (
        select(LibraryFacet, book_count)
        .outerjoin(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
        .outerjoin(LibraryBook, LibraryBook.id == LibraryBookFacet.book_id)
        .where(LibraryFacet.kind == normalized_kind)
        .group_by(LibraryFacet.id)
        .order_by(book_count.desc(), LibraryFacet.name.collate("NOCASE").asc())
    )

    search_clause = _facet_search_clause(search)
    if search_clause is not None:
        statement = statement.where(search_clause)
    if limit is not None:
        statement = statement.limit(limit).offset(offset)

    rows = db.execute(statement).all()
    return [_facet_public_dict(facet, int(count or 0)) for facet, count in rows]


def list_categories_page(
    db: Session,
    kind: str,
    search: str = "",
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return an indexed category page, its exact total, and the clamped page."""

    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    if page <= 0 or page_size <= 0:
        raise ValueError("分页参数无效")

    count_link = aliased(LibraryBookFacet)
    count_work = aliased(LibraryBook)
    visible_work = exists(
        select(count_work.id).where(
            count_work.id == count_link.book_id,
            func.coalesce(count_work.hidden, 0) == 0,
        )
    )
    book_count = (
        select(func.count())
        .select_from(count_link)
        .where(
            count_link.facet_id == LibraryFacet.id,
            visible_work,
        )
        .correlate(LibraryFacet)
        .scalar_subquery()
    )
    filters = [LibraryFacet.kind == normalized_kind]
    search_clause = _facet_search_clause(search)
    if search_clause is not None:
        filters.append(search_clause)
    base_statement = (
        select(
            LibraryFacet,
            book_count.label("book_count"),
            func.count().over().label("total_count"),
        )
        .where(*filters)
        .order_by(
            book_count.desc(),
            LibraryFacet.name.collate("NOCASE").asc(),
            LibraryFacet.id.asc(),
        )
    )

    def fetch(target_page: int) -> list[Any]:
        return db.execute(
            base_statement.limit(page_size).offset((target_page - 1) * page_size)
        ).all()

    rows = fetch(page)
    if rows:
        total = int(rows[0].total_count)
        return (
            [_facet_public_dict(row[0], int(row.book_count or 0)) for row in rows],
            total,
            page,
        )

    total = int(
        db.scalar(select(func.count()).select_from(LibraryFacet).where(*filters)) or 0
    )
    clamped_page = min(page, max(1, (total + page_size - 1) // page_size))
    if total and clamped_page != page:
        rows = fetch(clamped_page)
    return (
        [_facet_public_dict(row[0], int(row.book_count or 0)) for row in rows],
        total,
        clamped_page,
    )
