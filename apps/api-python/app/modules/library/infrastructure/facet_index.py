"""SQLAlchemy repository for bounded facet index repair batches."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha1

from sqlalchemy import (
    String,
    and_,
    column,
    delete,
    literal,
    or_,
    select,
    true,
    tuple_,
    update,
    values,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import db_timestamp
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_index import (
    PendingFacetWork,
    PreparedWorkFacets,
)
from app.modules.library.domain.facets import CURRENT_FACET_INDEX_VERSION


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

        now = db_timestamp()
        facets = _unique_facet_values(batch)
        facet_keys_by_work = {
            work.source.id: tuple(
                (facet.kind, facet.normalized_name) for facet in work.facets
            )
            for work in batch
        }
        source_matches = tuple(
            and_(
                LibraryWork.id == work.source.id,
                LibraryWork.author == work.source.author,
                LibraryWork.tags == work.source.tags_source,
                LibraryWork.series_name == work.source.series_name,
            )
            for work in batch
        )
        facet_candidate_rows = tuple(
            (
                work.source.id,
                work.source.author,
                work.source.tags_source,
                work.source.series_name,
                facets[(facet.kind, facet.normalized_name)][1],
                facet.kind,
                facets[(facet.kind, facet.normalized_name)][0],
                facet.normalized_name,
                facet.sort_order,
                now,
                now,
            )
            for work in batch
            for facet in work.facets
        )
        facet_insert_statements = []
        link_insert_statements = []
        for index, chunk in enumerate(
            sqlite_parameter_chunks(
                facet_candidate_rows,
                parameters_per_row=11,
                fixed_parameters=1,
            )
        ):
            candidates = (
                values(
                    column("work_id", String()),
                    column("author", String()),
                    column("tags_source", String()),
                    column("series_name", String()),
                    column("facet_id", String()),
                    column("kind", String()),
                    column("name", String()),
                    column("normalized_name", String()),
                    column("sort_order"),
                    column("created_at", LibraryFacet.__table__.c.createdAt.type),
                    column("updated_at", LibraryFacet.__table__.c.updatedAt.type),
                    name=f"facet_candidates_{index}",
                )
                .data(list(chunk))
                .cte()
            )
            stable_source = and_(
                LibraryWork.id == candidates.c.work_id,
                LibraryWork.author.is_not_distinct_from(candidates.c.author),
                LibraryWork.tags == candidates.c.tags_source,
                LibraryWork.series_name.is_not_distinct_from(
                    candidates.c.series_name
                ),
                LibraryWork.facet_index_version == index_version,
            )
            facet_insert_statements.append(
                sqlite_insert(LibraryFacet)
                .from_select(
                    [
                        LibraryFacet.id,
                        LibraryFacet.kind,
                        LibraryFacet.name,
                        LibraryFacet.normalized_name,
                        LibraryFacet.aliases,
                        LibraryFacet.created_at,
                        LibraryFacet.updated_at,
                    ],
                    select(
                        candidates.c.facet_id,
                        candidates.c.kind,
                        candidates.c.name,
                        candidates.c.normalized_name,
                        literal("[]"),
                        candidates.c.created_at,
                        candidates.c.updated_at,
                    )
                    .join(LibraryWork, stable_source)
                    .distinct()
                    .where(true()),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryFacet.kind,
                        LibraryFacet.normalized_name,
                    ]
                )
            )
            link_insert_statements.append(
                sqlite_insert(LibraryWorkFacet)
                .from_select(
                    [
                        LibraryWorkFacet.facet_id,
                        LibraryWorkFacet.work_id,
                        LibraryWorkFacet.sort_order,
                        LibraryWorkFacet.created_at,
                    ],
                    select(
                        LibraryFacet.id,
                        candidates.c.work_id,
                        candidates.c.sort_order,
                        candidates.c.created_at,
                    )
                    .join(LibraryWork, stable_source)
                    .join(
                        LibraryFacet,
                        and_(
                            LibraryFacet.kind == candidates.c.kind,
                            LibraryFacet.normalized_name
                            == candidates.c.normalized_name,
                        ),
                    )
                    .where(true()),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryWorkFacet.facet_id,
                        LibraryWorkFacet.work_id,
                    ]
                )
            )
        mapping_statements = tuple(
            select(
                LibraryFacet.kind,
                LibraryFacet.normalized_name,
                LibraryFacet.id,
            ).where(
                tuple_(LibraryFacet.kind, LibraryFacet.normalized_name).in_(chunk)
            )
            for chunk in sqlite_parameter_chunks(
                tuple(facets),
                parameters_per_row=2,
            )
        )
        work_candidates = (
            values(
                column("work_id", String()),
                column("author", String()),
                column("tags_source", String()),
                column("series_name", String()),
                name="stable_facet_works",
            )
            .data(
                [
                    (
                        work.source.id,
                        work.source.author,
                        work.source.tags_source,
                        work.source.series_name,
                    )
                    for work in batch
                ]
            )
            .cte()
        )
        persisted_work_ids = select(work_candidates.c.work_id).join(
            LibraryWork,
            and_(
                LibraryWork.id == work_candidates.c.work_id,
                LibraryWork.author.is_not_distinct_from(work_candidates.c.author),
                LibraryWork.tags == work_candidates.c.tags_source,
                LibraryWork.series_name.is_not_distinct_from(
                    work_candidates.c.series_name
                ),
                LibraryWork.facet_index_version == index_version,
            ),
        )
        delete_links_statement = delete(LibraryWorkFacet).where(
            LibraryWorkFacet.work_id.in_(persisted_work_ids)
        )

        # This compare-and-set is the first write. All parsing, hashing, row
        # construction, chunking and typed statement construction above has
        # completed before SQLite's single writer slot is acquired.
        unchanged_ids = set(
            self._db.scalars(
                update(LibraryWork)
                .where(
                    or_(*source_matches),
                    LibraryWork.facet_index_version < index_version,
                )
                .values(
                    facet_index_version=index_version,
                    updated_at=LibraryWork.updated_at,
                )
                .returning(LibraryWork.id)
            )
        )
        if not unchanged_ids:
            return 0

        for statement in facet_insert_statements:
            self._db.execute(statement)
        facet_ids: dict[tuple[str, str], str] = {}
        for statement in mapping_statements:
            rows = self._db.execute(statement)
            facet_ids.update(
                {(str(row.kind), str(row.normalized_name)): str(row.id) for row in rows}
            )
        expected_keys = {
            key
            for work_id in unchanged_ids
            for key in facet_keys_by_work[work_id]
        }
        missing = expected_keys - set(facet_ids)
        if missing:
            raise RuntimeError(
                f"facet index mapping incomplete; missing_count={len(missing)}"
            )
        self._db.execute(delete_links_statement)
        for statement in link_insert_statements:
            self._db.execute(statement)
        return len(unchanged_ids)
