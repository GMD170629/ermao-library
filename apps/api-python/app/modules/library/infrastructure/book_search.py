"""Indexed substring candidates with the existing SQLite LIKE semantics."""

import re

from sqlalchemy import ColumnElement, exists, func, or_, select, union
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.selectable import Select

from app.models import LibraryBookMetadata, book_search_index


def _metadata_search_condition(pattern: str) -> ColumnElement[bool]:
    return or_(
        func.lower(LibraryBookMetadata.title).like(pattern),
        func.lower(func.coalesce(LibraryBookMetadata.author, "")).like(pattern),
        func.lower(func.coalesce(LibraryBookMetadata.series_name, "")).like(pattern),
        func.lower(func.coalesce(LibraryBookMetadata.description, "")).like(pattern),
    )


def book_matches_search(
    book_id: ColumnElement[str] | InstrumentedAttribute[str], term: str
) -> ColumnElement[bool]:
    """Recheck a selected Book through its searchable covering-index range."""
    return exists(select(LibraryBookMetadata.book_id).where(
        LibraryBookMetadata.book_id.between(book_id, book_id),
        _metadata_search_condition(f"%{term}%"),
    ).correlate_except(LibraryBookMetadata))


def matching_search_book_ids(term: str) -> Select[tuple[str]]:
    pattern = f"%{term}%"
    # Trigram LIKE can index a literal sequence of at least three characters.
    # Short/wildcard-only sequences retain the prior covering scan, with no
    # new minimum search length or change to wildcard/null handling.
    if "\0" not in term and any(len(part) >= 3 for part in re.split(r"[%_]", term)):
        matches = union(
            *(
                select(book_search_index.c.bookId).where(
                    book_search_index.c[name].like(pattern)
                )
                for name in ("title", "author", "seriesName", "description")
            )
        ).subquery()
        return select(matches.c.bookId)
    return select(LibraryBookMetadata.book_id).where(_metadata_search_condition(pattern))
