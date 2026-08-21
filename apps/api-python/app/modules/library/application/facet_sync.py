"""Pure preparation contracts for synchronous work-facet replacement."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.library.domain.facets import (
    BookFacetValue,
    build_book_facet_values,
    parse_tag_names,
)


@dataclass(frozen=True, slots=True)
class BookFacetProjection:
    book_id: str
    author: str | None
    tags_source: str
    series_name: str | None


@dataclass(frozen=True, slots=True)
class PreparedBookFacet:
    book_id: str
    facets: tuple[BookFacetValue, ...]


def prepare_book_facet(projection: BookFacetProjection) -> PreparedBookFacet:
    """Parse, normalize, order and deduplicate one projection without a Session."""

    return PreparedBookFacet(
        book_id=projection.book_id,
        facets=build_book_facet_values(
            author=projection.author,
            tags=parse_tag_names(projection.tags_source),
            series_name=projection.series_name,
        ),
    )
