"""Pure preparation contracts for synchronous work-facet replacement."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.library.domain.facets import (
    WorkFacetValue,
    build_work_facet_values,
    parse_tag_names,
)


@dataclass(frozen=True, slots=True)
class WorkFacetProjection:
    work_id: str
    author: str | None
    tags_source: str
    series_name: str | None


@dataclass(frozen=True, slots=True)
class PreparedWorkFacet:
    work_id: str
    facets: tuple[WorkFacetValue, ...]


def prepare_work_facet(projection: WorkFacetProjection) -> PreparedWorkFacet:
    """Parse, normalize, order and deduplicate one projection without a Session."""

    return PreparedWorkFacet(
        work_id=projection.work_id,
        facets=build_work_facet_values(
            author=projection.author,
            tags=parse_tag_names(projection.tags_source),
            series_name=projection.series_name,
        ),
    )
