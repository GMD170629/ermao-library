"""Restartable application use case for rebuilding persisted work facets."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self

from app.modules.library.domain.facets import (
    CURRENT_FACET_INDEX_VERSION,
    WorkFacetValue,
    build_work_facet_values,
)


@dataclass(frozen=True, slots=True)
class PendingFacetWork:
    id: str
    author: str | None
    tags_source: str
    tags: tuple[str, ...]
    series_name: str | None


@dataclass(frozen=True, slots=True)
class PreparedWorkFacets:
    source: PendingFacetWork
    facets: tuple[WorkFacetValue, ...]


class FacetIndexRepository(Protocol):
    def pending_works(self, *, limit: int) -> tuple[PendingFacetWork, ...]: ...

    def replace_batch(
        self,
        batch: tuple[PreparedWorkFacets, ...],
        *,
        index_version: int,
    ) -> int: ...


class FacetIndexUnitOfWork(Protocol):
    facets: FacetIndexRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class FacetIndexUnitOfWorkFactory(Protocol):
    def __call__(self) -> FacetIndexUnitOfWork: ...


@dataclass(frozen=True)
class FacetIndexBatchResult:
    processed: int
    may_have_more: bool


@dataclass(frozen=True)
class RebuildFacetIndexBatch:
    unit_of_work_factory: FacetIndexUnitOfWorkFactory

    def execute(self, *, limit: int = 200) -> FacetIndexBatchResult:
        if not 1 <= limit <= 200:
            raise ValueError("facet index batch limit must be between 1 and 200")
        with self.unit_of_work_factory() as unit_of_work:
            pending = unit_of_work.facets.pending_works(limit=limit)
            batch = tuple(
                PreparedWorkFacets(
                    source=work,
                    facets=build_work_facet_values(
                        author=work.author,
                        tags=work.tags,
                        series_name=work.series_name,
                    ),
                )
                for work in pending
            )
            processed = unit_of_work.facets.replace_batch(
                batch,
                index_version=CURRENT_FACET_INDEX_VERSION,
            )
            unit_of_work.commit()
        return FacetIndexBatchResult(
            processed=processed,
            may_have_more=len(pending) == limit or processed < len(pending),
        )
