"""Set-based SQLite adapter for historical EPUB navigation maintenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    String,
    and_,
    case,
    column,
    delete,
    exists,
    or_,
    select,
    tuple_,
    update,
    values,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.contracts.epub_navigation import (
    EPUB_HREF_BASE_METADATA_KEY,
    EPUB_PUBLICATION_ROOT_HREF_BASE,
)
from app.core.sql_batches import sqlite_parameter_chunks
from app.models.library import LibraryFile, LibraryReadingUnit, LibraryVolume
from app.modules.reader.application.navigation_maintenance import (
    PendingEpubNavigation,
    PreparedEpubNavigation,
)


def _navigation_metadata(idref: str | None) -> str:
    return json.dumps(
        {
            "idref": idref,
            "recovered": True,
            EPUB_HREF_BASE_METADATA_KEY: EPUB_PUBLICATION_ROOT_HREF_BASE,
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class PreparedEpubNavigationWrite:
    statements: tuple[Executable, ...]
    result_statement: Executable


def prepare_epub_navigation_write(
    batch: tuple[PreparedEpubNavigation, ...],
    *,
    now: datetime,
) -> PreparedEpubNavigationWrite:
    """Build rows, chunks and every typed statement before opening a write UoW."""

    unique_batch = tuple(
        {prepared.source.volume_id: prepared for prepared in batch}.values()
    )
    if not unique_batch:
        raise ValueError("EPUB navigation write batch must not be empty")
    source_keys = tuple(
        (
            prepared.source.file_id,
            prepared.source.volume_id,
            prepared.source.source_updated_at,
        )
        for prepared in unique_batch
    )
    current_volume_ids = (
        select(LibraryFile.volume_id)
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .where(
            tuple_(
                LibraryFile.id,
                LibraryFile.volume_id,
                LibraryFile.updated_at,
            ).in_(source_keys),
            LibraryFile.kind == "EPUB",
            LibraryVolume.format == "EPUB",
        )
    )
    delete_statement = delete(LibraryReadingUnit).where(
        LibraryReadingUnit.volume_id.in_(current_volume_ids),
        LibraryReadingUnit.unit_type == "chapter",
    )
    chapter_rows = tuple(
        {
            "id": "recovered_"
            + hashlib.sha256(
                (
                    f"{prepared.source.volume_id}\0{chapter.sort_order}\0{chapter.href}"
                ).encode()
            ).hexdigest()[:32],
            "volume_id": prepared.source.volume_id,
            "file_id": prepared.source.file_id,
            "unit_type": "chapter",
            "title": chapter.title,
            "href": chapter.href,
            "media_type": chapter.media_type,
            "sort_order": chapter.sort_order,
            "metadata_json": _navigation_metadata(chapter.idref),
            "created_at": now,
            "updated_at": now,
            "source_updated_at": prepared.source.source_updated_at,
        }
        for prepared in unique_batch
        for chapter in prepared.chapters
    )
    insert_statements: list[Executable] = []
    for index, chunk in enumerate(
        sqlite_parameter_chunks(chapter_rows, parameters_per_row=12)
    ):
        candidates = (
            values(
                column("id", String()),
                column("volume_id", String()),
                column("file_id", String()),
                column("unit_type", String()),
                column("title", String()),
                column("href", String()),
                column("media_type", String()),
                column("sort_order"),
                column("metadata_json", String()),
                column("created_at", LibraryReadingUnit.created_at.type),
                column("updated_at", LibraryReadingUnit.updated_at.type),
                column("source_updated_at", LibraryFile.updated_at.type),
                name=f"epub_navigation_candidates_{index}",
            )
            .data(
                [
                    (
                        row["id"],
                        row["volume_id"],
                        row["file_id"],
                        row["unit_type"],
                        row["title"],
                        row["href"],
                        row["media_type"],
                        row["sort_order"],
                        row["metadata_json"],
                        row["created_at"],
                        row["updated_at"],
                        row["source_updated_at"],
                    )
                    for row in chunk
                ]
            )
            .cte()
        )
        insert_statements.append(
            sqlite_insert(LibraryReadingUnit).from_select(
                [
                    LibraryReadingUnit.id,
                    LibraryReadingUnit.volume_id,
                    LibraryReadingUnit.file_id,
                    LibraryReadingUnit.unit_type,
                    LibraryReadingUnit.title,
                    LibraryReadingUnit.href,
                    LibraryReadingUnit.media_type,
                    LibraryReadingUnit.sort_order,
                    LibraryReadingUnit.metadata_json,
                    LibraryReadingUnit.created_at,
                    LibraryReadingUnit.updated_at,
                ],
                select(
                    candidates.c.id,
                    candidates.c.volume_id,
                    candidates.c.file_id,
                    candidates.c.unit_type,
                    candidates.c.title,
                    candidates.c.href,
                    candidates.c.media_type,
                    candidates.c.sort_order,
                    candidates.c.metadata_json,
                    candidates.c.created_at,
                    candidates.c.updated_at,
                )
                .join(
                    LibraryFile,
                    and_(
                        LibraryFile.id == candidates.c.file_id,
                        LibraryFile.volume_id == candidates.c.volume_id,
                        LibraryFile.updated_at == candidates.c.source_updated_at,
                        LibraryFile.kind == "EPUB",
                    ),
                )
                .join(
                    LibraryVolume,
                    and_(
                        LibraryVolume.id == candidates.c.volume_id,
                        LibraryVolume.format == "EPUB",
                    ),
                ),
            )
        )
    chapter_counts = {
        prepared.source.volume_id: len(prepared.chapters) for prepared in unique_batch
    }
    update_statement = (
        update(LibraryVolume)
        .where(LibraryVolume.id.in_(current_volume_ids))
        .values(
            chapter_count=case(chapter_counts, value=LibraryVolume.id),
            updated_at=now,
        )
    )
    return PreparedEpubNavigationWrite(
        statements=(delete_statement, *insert_statements),
        result_statement=update_statement,
    )


class SqlAlchemyEpubNavigationMaintenanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(
        self, *, limit: int, after_volume_id: str | None
    ) -> tuple[PendingEpubNavigation, ...]:
        any_chapter = exists(
            select(LibraryReadingUnit.id).where(
                LibraryReadingUnit.volume_id == LibraryVolume.id,
                LibraryReadingUnit.unit_type == "chapter",
            )
        )
        valid_marker = or_(
            LibraryReadingUnit.metadata_json.contains(
                f'"{EPUB_HREF_BASE_METADATA_KEY}": "{EPUB_PUBLICATION_ROOT_HREF_BASE}"'
            ),
            LibraryReadingUnit.metadata_json.contains(
                f'"{EPUB_HREF_BASE_METADATA_KEY}":"{EPUB_PUBLICATION_ROOT_HREF_BASE}"'
            ),
        )
        invalid_chapter = exists(
            select(LibraryReadingUnit.id).where(
                LibraryReadingUnit.volume_id == LibraryVolume.id,
                LibraryReadingUnit.unit_type == "chapter",
                ~valid_marker,
            )
        )
        first_epub_file_id = (
            select(LibraryFile.id)
            .where(
                LibraryFile.volume_id == LibraryVolume.id,
                LibraryFile.kind == "EPUB",
            )
            .order_by(
                LibraryFile.sort_order.asc(),
                LibraryFile.created_at.asc(),
                LibraryFile.id.asc(),
            )
            .limit(1)
            .correlate(LibraryVolume)
            .scalar_subquery()
        )
        statement = (
            select(
                LibraryVolume.id.label("volume_id"),
                LibraryFile.id.label("file_id"),
                LibraryFile.path.label("source_path"),
                LibraryFile.updated_at.label("source_updated_at"),
            )
            .join(LibraryFile, LibraryFile.id == first_epub_file_id)
            .where(
                LibraryVolume.format == "EPUB",
                or_(~any_chapter, invalid_chapter),
            )
            .order_by(LibraryVolume.id.asc())
            .limit(limit)
        )
        if after_volume_id is not None:
            statement = statement.where(LibraryVolume.id > after_volume_id)
        return tuple(
            PendingEpubNavigation(
                volume_id=str(row.volume_id),
                file_id=str(row.file_id),
                source_path=str(row.source_path),
                source_updated_at=row.source_updated_at,
            )
            for row in self._session.execute(statement)
        )

    def execute_prepared(self, prepared: PreparedEpubNavigationWrite) -> int:
        for statement in prepared.statements:
            self._session.execute(statement)
        result = self._session.execute(prepared.result_statement)
        return int(result.rowcount or 0)
