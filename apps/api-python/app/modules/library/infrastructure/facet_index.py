"""SQLAlchemy repository for bounded facet index repair batches."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from hashlib import sha1
from typing import TypeVar

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_index import (
    PendingFacetWork,
    PreparedWorkFacets,
)
from app.modules.library.domain.facets import CURRENT_FACET_INDEX_VERSION
from app.modules.library.infrastructure.facets import work_tags

BatchValue = TypeVar("BatchValue")
SQLITE_WRITE_CHUNK_SIZE = 100


def _chunks(
    values: tuple[BatchValue, ...], size: int = SQLITE_WRITE_CHUNK_SIZE
) -> Iterator[tuple[BatchValue, ...]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _facet_id(kind: str, normalized_name: str) -> str:
    digest = sha1(f"{kind}\0{normalized_name}".encode()).hexdigest()[:24]
    return f"facet_{digest}"


def _pending_work(
    work_id: object,
    author: object,
    tags_json: object,
    series_name: object,
) -> PendingFacetWork:
    tags_source = str(tags_json) if tags_json is not None else "[]"
    return PendingFacetWork(
        id=str(work_id),
        author=str(author) if author is not None else None,
        tags_source=tags_source,
        tags=tuple(work_tags(tags_source)),
        series_name=str(series_name) if series_name is not None else None,
    )


def _unique_facet_values(
    batch: Iterable[PreparedWorkFacets],
) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for work in batch:
        for facet in work.facets:
            key = (facet.kind, facet.normalized_name)
            result.setdefault(key, (facet.name, _facet_id(*key)))
    return result


class SqlAlchemyFacetIndexRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def pending_works(self, *, limit: int) -> tuple[PendingFacetWork, ...]:
        return tuple(
            _pending_work(*row)
            for row in self._db.execute(
                select(
                    LibraryWork.id,
                    LibraryWork.author,
                    LibraryWork.tags,
                    LibraryWork.series_name,
                )
                .where(LibraryWork.facet_index_version < CURRENT_FACET_INDEX_VERSION)
                .order_by(LibraryWork.id.asc())
                .limit(limit)
            )
        )

    def replace_batch(
        self,
        batch: tuple[PreparedWorkFacets, ...],
        *,
        index_version: int,
    ) -> int:
        if not batch:
            return 0
        candidate_ids = tuple(work.source.id for work in batch)

        # A no-op update acquires SQLite's single writer slot. Keeping both
        # values explicit prevents SQLAlchemy's on-update timestamp from
        # turning index maintenance into a user-visible metadata edit.
        self._db.execute(
            update(LibraryWork)
            .where(
                LibraryWork.id.in_(candidate_ids),
                LibraryWork.facet_index_version < index_version,
            )
            .values(
                facet_index_version=LibraryWork.facet_index_version,
                updated_at=LibraryWork.updated_at,
            )
        )
        current_by_id = {
            work.id: work
            for work in (
                _pending_work(*row)
                for row in self._db.execute(
                    select(
                        LibraryWork.id,
                        LibraryWork.author,
                        LibraryWork.tags,
                        LibraryWork.series_name,
                    ).where(
                        LibraryWork.id.in_(candidate_ids),
                        LibraryWork.facet_index_version < index_version,
                    )
                )
            )
        }
        unchanged = tuple(
            work
            for work in batch
            if current_by_id.get(work.source.id) == work.source
        )
        if not unchanged:
            return 0

        now = db_timestamp()
        facets = _unique_facet_values(unchanged)
        facet_items = tuple(facets.items())
        for chunk in _chunks(facet_items):
            self._db.execute(
                sqlite_insert(LibraryFacet)
                .values(
                    [
                        {
                            "id": facet_id,
                            "kind": kind,
                            "name": name,
                            "normalized_name": normalized_name,
                            "aliases": "[]",
                            "created_at": now,
                            "updated_at": now,
                        }
                        for (kind, normalized_name), (name, facet_id) in chunk
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryFacet.kind,
                        LibraryFacet.normalized_name,
                    ]
                )
            )

        facet_ids: dict[tuple[str, str], str] = {}
        facet_keys = tuple(facets)
        for chunk in _chunks(facet_keys):
            rows = self._db.execute(
                select(
                    LibraryFacet.kind,
                    LibraryFacet.normalized_name,
                    LibraryFacet.id,
                ).where(
                    tuple_(LibraryFacet.kind, LibraryFacet.normalized_name).in_(chunk)
                )
            )
            facet_ids.update(
                {
                    (str(row.kind), str(row.normalized_name)): str(row.id)
                    for row in rows
                }
            )
        missing = set(facet_keys) - set(facet_ids)
        if missing:
            raise RuntimeError(
                f"facet index mapping incomplete; missing_count={len(missing)}"
            )

        work_ids = tuple(work.source.id for work in unchanged)
        self._db.execute(
            delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id.in_(work_ids))
        )
        links = tuple(
            {
                "facet_id": facet_ids[(facet.kind, facet.normalized_name)],
                "work_id": work.source.id,
                "sort_order": facet.sort_order,
                "created_at": now,
            }
            for work in unchanged
            for facet in work.facets
        )
        for chunk in _chunks(links):
            self._db.execute(
                sqlite_insert(LibraryWorkFacet)
                .values(list(chunk))
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryWorkFacet.facet_id,
                        LibraryWorkFacet.work_id,
                    ]
                )
            )
        self._db.execute(
            update(LibraryWork)
            .where(
                LibraryWork.id.in_(work_ids),
                LibraryWork.facet_index_version < index_version,
            )
            .values(
                facet_index_version=index_version,
                updated_at=LibraryWork.updated_at,
            )
        )
        return len(unchanged)
