"""Indexed substring candidates with the existing SQLite LIKE semantics."""

import re

from sqlalchemy import func, or_, select, union
from sqlalchemy.sql.selectable import Select

from app.models import LibraryBookMetadata, book_search_index


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
    return select(LibraryBookMetadata.book_id).where(
        or_(
            func.lower(LibraryBookMetadata.title).like(pattern),
            func.lower(func.coalesce(LibraryBookMetadata.author, "")).like(pattern),
            func.lower(func.coalesce(LibraryBookMetadata.series_name, "")).like(
                pattern
            ),
            func.lower(func.coalesce(LibraryBookMetadata.description, "")).like(
                pattern
            ),
        )
    )
