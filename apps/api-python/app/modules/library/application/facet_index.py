"""Restartable application use case for rebuilding persisted work facets."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self


class FacetIndexRepository(Protocol):
    def pending_work_ids(self, *, limit: int) -> tuple[str, ...]: ...

    def rebuild_work(self, work_id: str) -> None: ...


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
            work_ids = unit_of_work.facets.pending_work_ids(limit=limit)
            for work_id in work_ids:
                unit_of_work.facets.rebuild_work(work_id)
            unit_of_work.commit()
        return FacetIndexBatchResult(
            processed=len(work_ids),
            may_have_more=len(work_ids) == limit,
        )
