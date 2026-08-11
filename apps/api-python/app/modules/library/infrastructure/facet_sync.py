"""Set-based SQL persistence for already prepared synchronous facets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1

from sqlalchemy import String, and_, column, delete, select, update, values
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_sync import (
    PreparedWorkFacet,
    WorkFacetProjection,
)
from app.modules.library.domain.facets import CURRENT_FACET_INDEX_VERSION


@dataclass(frozen=True, slots=True)
class PreparedWorkFacetWrite:
    statements: tuple[Executable, ...]


def _facet_id(kind: str, normalized_name: str) -> str:
    digest = sha1(f"{kind}\0{normalized_name}".encode()).hexdigest()[:24]
    return f"facet_{digest}"


def load_work_facet_projections(
    db: Session, work_ids: tuple[str, ...]
) -> tuple[WorkFacetProjection, ...]:
    if not work_ids:
        return ()
    return tuple(
        WorkFacetProjection(
            work_id=str(row.id),
            author=str(row.author) if row.author is not None else None,
            tags_source=str(row.tags) if row.tags is not None else "[]",
            series_name=(
                str(row.series_name) if row.series_name is not None else None
            ),
        )
        for row in db.execute(
            select(
                LibraryWork.id,
                LibraryWork.author,
                LibraryWork.tags,
                LibraryWork.series_name,
            ).where(LibraryWork.id.in_(work_ids))
        )
    )


def prepare_work_facet_write(
    prepared_works: tuple[PreparedWorkFacet, ...],
    *,
    now: datetime,
) -> PreparedWorkFacetWrite:
    """Construct every bind row and typed statement before the first DML."""

    unique_works = tuple(
        {work.work_id: work for work in prepared_works if work.work_id}.values()
    )
    if not unique_works:
        return PreparedWorkFacetWrite(())

    facets: dict[tuple[str, str], tuple[str, str]] = {}
    for work in unique_works:
        for facet in work.facets:
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

    work_ids = tuple(work.work_id for work in unique_works)
    delete_statement = delete(LibraryWorkFacet).where(
        LibraryWorkFacet.work_id.in_(work_ids)
    )
    link_rows = tuple(
        (
            work.work_id,
            facet.kind,
            facet.normalized_name,
            facet.sort_order,
            now,
        )
        for work in unique_works
        for facet in work.facets
    )
    link_statements: list[Executable] = []
    for index, chunk in enumerate(
        sqlite_parameter_chunks(link_rows, parameters_per_row=5)
    ):
        candidates = (
            values(
                column("work_id", String()),
                column("kind", String()),
                column("normalized_name", String()),
                column("sort_order"),
                column("created_at", LibraryWorkFacet.__table__.c.createdAt.type),
                name=f"synchronous_facet_links_{index}",
            )
            .data(list(chunk))
            .cte()
        )
        link_statements.append(
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
                ).join(
                    LibraryFacet,
                    and_(
                        LibraryFacet.kind == candidates.c.kind,
                        LibraryFacet.normalized_name
                        == candidates.c.normalized_name,
                    ),
                ),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    LibraryWorkFacet.facet_id,
                    LibraryWorkFacet.work_id,
                ]
            )
        )

    version_statement = (
        update(LibraryWork)
        .where(LibraryWork.id.in_(work_ids))
        .values(
            facet_index_version=CURRENT_FACET_INDEX_VERSION,
            updated_at=LibraryWork.updated_at,
        )
    )
    return PreparedWorkFacetWrite(
        (*facet_statements, delete_statement, *link_statements, version_statement)
    )


def execute_work_facet_write(
    db: Session, prepared: PreparedWorkFacetWrite
) -> None:
    for statement in prepared.statements:
        db.execute(statement)
