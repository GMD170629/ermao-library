"""ORM persistence for LibraryFacet rows and work/edition facet links."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from hashlib import sha1
from typing import Any

from sqlalchemy import case, delete, distinct, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.time import to_timestamp_ms
from app.models.common import db_timestamp
from app.models.library import (
    LibraryEdition,
    LibraryEditionFacet,
    LibraryFacet,
    LibraryWork,
    LibraryWorkFacet,
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


def work_tags(value: Any) -> list[str]:
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
        .on_conflict_do_nothing(index_elements=[LibraryFacet.kind, LibraryFacet.normalized_name])
    )
    existing = db.execute(
        select(LibraryFacet.id).where(
            LibraryFacet.kind == kind,
            LibraryFacet.normalized_name == normalized,
        )
    ).scalar_one()
    return str(existing)


def _optional_scalar(db: Session, statement: Any) -> Any:
    """Read an optional fixture column without aborting the surrounding transaction."""

    try:
        with db.begin_nested():
            return db.execute(statement).scalar_one_or_none()
    except OperationalError:
        return None


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


def sync_work_facets(db: Session, work_id: str) -> None:
    """Synchronize persisted facets for one work after a runtime library change."""

    try:
        with db.begin_nested():
            work = db.execute(
                select(
                    LibraryWork.id,
                    LibraryWork.author,
                    LibraryWork.tags,
                ).where(LibraryWork.id == work_id)
            ).one_or_none()
    except OperationalError:
        return
    if work is None:
        return

    series_name = _optional_scalar(
        db,
        select(LibraryWork.series_name).where(LibraryWork.id == work_id),
    )
    now = db_timestamp()
    db.execute(delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id))
    work_values = {
        "AUTHOR": split_authors(work.author),
        "TAG": work_tags(work.tags),
        "SERIES": unique_names([series_name]),
    }
    for kind, names in work_values.items():
        for sort_order, name in enumerate(names):
            facet_id = ensure_facet(db, kind, name)
            db.execute(
                sqlite_insert(LibraryWorkFacet)
                .values(
                    facet_id=facet_id,
                    work_id=work_id,
                    sort_order=sort_order,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[LibraryWorkFacet.facet_id, LibraryWorkFacet.work_id]
                )
            )

    try:
        with db.begin_nested():
            editions = db.execute(
                select(LibraryEdition.id, LibraryEdition.publisher).where(
                    LibraryEdition.work_id == work_id
                )
            ).all()
    except OperationalError:
        editions = [
            (edition_id, None)
            for edition_id in db.execute(
                select(LibraryEdition.id).where(LibraryEdition.work_id == work_id)
            ).scalars()
        ]
    for edition in editions:
        edition_id = str(edition.id if hasattr(edition, "id") else edition[0])
        publisher = edition.publisher if hasattr(edition, "publisher") else edition[1]
        db.execute(delete(LibraryEditionFacet).where(LibraryEditionFacet.edition_id == edition_id))
        for publisher_name in unique_names([publisher]):
            facet_id = ensure_facet(db, "PUBLISHER", publisher_name)
            db.execute(
                sqlite_insert(LibraryEditionFacet)
                .values(
                    facet_id=facet_id,
                    edition_id=edition_id,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[LibraryEditionFacet.facet_id, LibraryEditionFacet.edition_id]
                )
            )
    db.flush()


def count_categories(db: Session, kind: str, search: str = "") -> int:
    normalized_kind = kind.strip().upper()
    if normalized_kind not in FACET_KINDS:
        raise ValueError("分类类型无效")
    statement = select(func.count()).select_from(LibraryFacet).where(LibraryFacet.kind == normalized_kind)
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

    if normalized_kind == "PUBLISHER":
        book_count = func.count(
            distinct(
                case(
                    (func.coalesce(LibraryWork.hidden, 0) == 0, LibraryEdition.work_id),
                )
            )
        ).label("bookCount")
        statement = (
            select(LibraryFacet, book_count)
            .outerjoin(LibraryEditionFacet, LibraryEditionFacet.facet_id == LibraryFacet.id)
            .outerjoin(LibraryEdition, LibraryEdition.id == LibraryEditionFacet.edition_id)
            .outerjoin(LibraryWork, LibraryWork.id == LibraryEdition.work_id)
            .where(LibraryFacet.kind == normalized_kind)
            .group_by(LibraryFacet.id)
            .order_by(book_count.desc(), LibraryFacet.name.collate("NOCASE").asc())
        )
    else:
        book_count = func.count(
            distinct(
                case(
                    (func.coalesce(LibraryWork.hidden, 0) == 0, LibraryWorkFacet.work_id),
                )
            )
        ).label("bookCount")
        statement = (
            select(LibraryFacet, book_count)
            .outerjoin(LibraryWorkFacet, LibraryWorkFacet.facet_id == LibraryFacet.id)
            .outerjoin(LibraryWork, LibraryWork.id == LibraryWorkFacet.work_id)
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
