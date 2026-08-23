"""Set-based SQL persistence for already prepared synchronous facets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1

from sqlalchemy import String, and_, column, delete, select, values
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
)
from app.modules.library.application.facet_sync import (
    BookFacetProjection,
    PreparedBookFacet,
)


@dataclass(frozen=True, slots=True)
class PreparedBookFacetWrite:
    statements: tuple[Executable, ...]


def _facet_id(kind: str, normalized_name: str) -> str:
    digest = sha1(f"{kind}\0{normalized_name}".encode()).hexdigest()[:24]
    return f"facet_{digest}"


def load_book_facet_projections(
    db: Session, book_ids: tuple[str, ...]
) -> tuple[BookFacetProjection, ...]:
    if not book_ids:
        return ()
    book_rows = db.execute(
        select(
            LibraryBook.id,
            LibraryBookMetadata.author,
            LibraryBookMetadata.series_name,
        )
        .select_from(LibraryBook)
        .outerjoin(
            LibraryBookMetadata,
            LibraryBookMetadata.book_id == LibraryBook.id,
        )
        .where(LibraryBook.id.in_(book_ids))
    ).all()
    tag_rows = db.execute(
        select(LibraryBookFacet.book_id, LibraryFacet.name)
        .join(LibraryFacet, LibraryFacet.id == LibraryBookFacet.facet_id)
        .where(
            LibraryBookFacet.book_id.in_(book_ids),
            LibraryFacet.kind == "TAG",
        )
        .order_by(LibraryBookFacet.book_id.asc(), LibraryBookFacet.sort_order.asc())
    ).all()
    tags_by_book: dict[str, list[str]] = {book_id: [] for book_id in book_ids}
    for row in tag_rows:
        tags_by_book.setdefault(str(row.book_id), []).append(str(row.name))
    return tuple(
        BookFacetProjection(
            book_id=str(row.id),
            author=str(row.author) if row.author is not None else None,
            tags_source=json.dumps(
                tags_by_book.get(str(row.id), []), ensure_ascii=False
            ),
            series_name=(str(row.series_name) if row.series_name is not None else None),
        )
        for row in book_rows
    )


def prepare_book_facet_write(
    prepared_books: tuple[PreparedBookFacet, ...],
    *,
    now: datetime,
) -> PreparedBookFacetWrite:
    """Construct every bind row and typed statement before the first DML."""

    unique_books = tuple(
        {book.book_id: book for book in prepared_books if book.book_id}.values()
    )
    if not unique_books:
        return PreparedBookFacetWrite(())

    facets: dict[tuple[str, str], tuple[str, str]] = {}
    for book in unique_books:
        for facet in book.facets:
            key = (facet.kind, facet.normalized_name)
            facets.setdefault(key, (facet.name, _facet_id(*key)))

    facet_rows = tuple(
        {
            "id": facet_id,
            "kind": kind,
            "name": name,
            "normalized_name": normalized_name,
            "aliases": "[]",
            "created_at": now,
            "updated_at": now,
        }
        for (kind, normalized_name), (name, facet_id) in facets.items()
    )
    facet_statements = tuple(
        sqlite_insert(LibraryFacet)
        .values(list(chunk))
        .on_conflict_do_nothing(
            index_elements=[LibraryFacet.kind, LibraryFacet.normalized_name]
        )
        for chunk in sqlite_parameter_chunks(facet_rows, parameters_per_row=7)
    )

    book_ids = tuple(book.book_id for book in unique_books)
    delete_statement = delete(LibraryBookFacet).where(
        LibraryBookFacet.book_id.in_(book_ids)
    )
    link_rows = tuple(
        (
            book.book_id,
            facet.kind,
            facet.normalized_name,
            facet.sort_order,
            now,
        )
        for book in unique_books
        for facet in book.facets
    )
    link_statements: list[Executable] = []
    for index, chunk in enumerate(
        sqlite_parameter_chunks(link_rows, parameters_per_row=5)
    ):
        candidates = (
            values(
                column("book_id", String()),
                column("kind", String()),
                column("normalized_name", String()),
                column("sort_order"),
                column("created_at", LibraryBookFacet.__table__.c.createdAt.type),
                name=f"synchronous_facet_links_{index}",
            )
            .data(list(chunk))
            .cte()
        )
        link_statements.append(
            sqlite_insert(LibraryBookFacet)
            .from_select(
                [
                    LibraryBookFacet.facet_id,
                    LibraryBookFacet.book_id,
                    LibraryBookFacet.sort_order,
                    LibraryBookFacet.created_at,
                ],
                select(
                    LibraryFacet.id,
                    candidates.c.book_id,
                    candidates.c.sort_order,
                    candidates.c.created_at,
                ).join(
                    LibraryFacet,
                    and_(
                        LibraryFacet.kind == candidates.c.kind,
                        LibraryFacet.normalized_name == candidates.c.normalized_name,
                    ),
                ),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    LibraryBookFacet.facet_id,
                    LibraryBookFacet.book_id,
                ]
            )
        )

    return PreparedBookFacetWrite(
        (*facet_statements, delete_statement, *link_statements)
    )


def execute_book_facet_write(db: Session, prepared: PreparedBookFacetWrite) -> None:
    for statement in prepared.statements:
        db.execute(statement)
