"""Typed SQLite and archive adapters for the comic page-index migration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    String,
    case,
    column,
    delete,
    func,
    literal,
    select,
    update,
    values,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.selectable import CTE

from app.contracts.comic_page_index import CURRENT_COMIC_PAGE_INDEX_VERSION
from app.core.config import Settings
from app.core.sql_batches import sqlite_parameter_chunks
from app.infrastructure.comic_archives import ComicArchiveError, inspect_comic_archive
from app.models.library import LibraryFile, LibraryReadingUnit, LibraryVolume
from app.modules.media.application.comic_page_index_migration import (
    ComicPageIndexPage,
    ComicPageIndexParseError,
    PendingComicPageIndex,
    PreparedComicPageIndex,
)
from app.modules.media.infrastructure.page_index import _stored_path


class FileComicPageIndexParser:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def parse(
        self, source: PendingComicPageIndex
    ) -> tuple[ComicPageIndexPage, ...]:
        archive_path = _stored_path(
            source.source_path,
            self._settings,
            database_backed=True,
        )
        if archive_path is None:
            raise ComicPageIndexParseError(
                f"comic source path is unavailable: {source.file_id}"
            )
        try:
            parsed = inspect_comic_archive(archive_path, Path(source.source_path).name)
        except (OSError, ValueError, ComicArchiveError) as error:
            raise ComicPageIndexParseError(
                f"comic source could not be inspected: {source.file_id}"
            ) from error
        return tuple(
            ComicPageIndexPage(
                index=int(page["index"]),
                title=str(page["title"]),
                entry_path=str(page["entryPath"]),
                media_type=str(page["mediaType"]),
                size=int(page["size"]),
            )
            for page in parsed["pages"]
        )


@dataclass(frozen=True, slots=True)
class PreparedComicPageIndexWrite:
    statements: tuple[Executable, ...]
    result_statement: Executable


def _source_values(
    name: str,
    batch: tuple[PreparedComicPageIndex, ...],
) -> CTE:
    return (
        values(
            column("file_id", String()),
            column("volume_id", String()),
            column("source_updated_at", LibraryFile.updated_at.type),
            column("source_size_bytes"),
            column("source_mtime_ms"),
            name=name,
        )
        .data(
            [
                (
                    prepared.source.file_id,
                    prepared.source.volume_id,
                    prepared.source.source_updated_at,
                    prepared.source.source_size_bytes,
                    prepared.source.source_mtime_ms,
                )
                for prepared in batch
            ]
        )
        .cte()
    )


def _valid_sources(source_values: CTE, name: str) -> CTE:
    return (
        select(
            source_values.c.file_id,
            source_values.c.volume_id,
        )
        .join(
            LibraryFile,
            (
                (LibraryFile.id == source_values.c.file_id)
                & (LibraryFile.volume_id == source_values.c.volume_id)
                & (LibraryFile.updated_at == source_values.c.source_updated_at)
                & (LibraryFile.size_bytes == source_values.c.source_size_bytes)
                & (LibraryFile.mtime_ms == source_values.c.source_mtime_ms)
            ),
        )
        .where(
            LibraryFile.kind == "COMIC",
            LibraryFile.page_index_version < CURRENT_COMIC_PAGE_INDEX_VERSION,
        )
        .cte(name)
    )


def _page_metadata(
    prepared: PreparedComicPageIndex,
    page: ComicPageIndexPage,
) -> str:
    return json.dumps(
        {
            "zipEntryName": page.entry_path,
            "originalName": Path(page.entry_path).name,
            "pageInVolume": page.index,
            "pageInSection": page.index,
            "volumeIndex": prepared.source.volume_index,
            "sourceFileName": Path(prepared.source.source_path).name,
        },
        ensure_ascii=False,
    )


def _page_id(prepared: PreparedComicPageIndex, page: ComicPageIndexPage) -> str:
    digest = hashlib.sha256(
        (
            f"{prepared.source.volume_id}\0{page.index}\0{page.entry_path}"
        ).encode()
    ).hexdigest()
    return f"comic_page_{digest[:40]}"


def prepare_comic_page_index_write(
    batch: tuple[PreparedComicPageIndex, ...],
    *,
    now: datetime,
) -> PreparedComicPageIndexWrite:
    """Prepare every row, chunk and SQL expression before the write UoW opens."""

    unique_batch = tuple(
        {prepared.source.file_id: prepared for prepared in batch}.values()
    )
    if not unique_batch:
        raise ValueError("comic page-index migration batch must not be empty")

    all_source_values = _source_values("comic_page_sources", unique_batch)
    valid_all_sources = _valid_sources(all_source_values, "valid_comic_page_sources")
    rebuild_batch = tuple(
        prepared for prepared in unique_batch if not prepared.reuse_existing
    )
    statements: list[Executable] = []
    if rebuild_batch:
        rebuild_source_values = _source_values(
            "comic_page_rebuild_sources",
            rebuild_batch,
        )
        valid_rebuild_sources = _valid_sources(
            rebuild_source_values,
            "valid_comic_page_rebuild_sources",
        )
        statements.append(
            delete(LibraryReadingUnit).where(
                LibraryReadingUnit.volume_id.in_(
                    select(valid_rebuild_sources.c.volume_id)
                ),
                LibraryReadingUnit.unit_type == "page",
            )
        )

        page_rows = tuple(
            {
                "id": _page_id(prepared, page),
                "file_id": prepared.source.file_id,
                "title": page.title,
                "href": page.entry_path,
                "media_type": page.media_type,
                "sort_order": page.index,
                "size": page.size,
                "metadata_json": _page_metadata(prepared, page),
            }
            for prepared in rebuild_batch
            for page in prepared.pages
        )
        for index, chunk in enumerate(
            sqlite_parameter_chunks(
                page_rows,
                parameters_per_row=8,
                fixed_parameters=2,
            )
        ):
            candidates = (
                values(
                    column("id", String()),
                    column("file_id", String()),
                    column("title", String()),
                    column("href", String()),
                    column("media_type", String()),
                    column("sort_order"),
                    column("size"),
                    column("metadata_json", String()),
                    name=f"comic_page_candidates_{index}",
                )
                .data(
                    [
                        (
                            row["id"],
                            row["file_id"],
                            row["title"],
                            row["href"],
                            row["media_type"],
                            row["sort_order"],
                            row["size"],
                            row["metadata_json"],
                        )
                        for row in chunk
                    ]
                )
                .cte()
            )
            statements.append(
                sqlite_insert(LibraryReadingUnit)
                .from_select(
                    [
                        LibraryReadingUnit.id,
                        LibraryReadingUnit.file_id,
                        LibraryReadingUnit.volume_id,
                        LibraryReadingUnit.unit_type,
                        LibraryReadingUnit.title,
                        LibraryReadingUnit.href,
                        LibraryReadingUnit.media_type,
                        LibraryReadingUnit.sort_order,
                        LibraryReadingUnit.size,
                        LibraryReadingUnit.metadata_json,
                        LibraryReadingUnit.created_at,
                        LibraryReadingUnit.updated_at,
                    ],
                    select(
                        candidates.c.id,
                        candidates.c.file_id,
                        valid_rebuild_sources.c.volume_id,
                        literal("page"),
                        candidates.c.title,
                        candidates.c.href,
                        candidates.c.media_type,
                        candidates.c.sort_order,
                        candidates.c.size,
                        candidates.c.metadata_json,
                        literal(now),
                        literal(now),
                    ).join(
                        valid_rebuild_sources,
                        valid_rebuild_sources.c.file_id == candidates.c.file_id,
                    ),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryReadingUnit.volume_id,
                        LibraryReadingUnit.unit_type,
                        LibraryReadingUnit.sort_order,
                    ]
                )
            )

    page_counts = {
        prepared.source.volume_id: prepared.page_count for prepared in unique_batch
    }
    statements.append(
        update(LibraryVolume)
        .where(
            LibraryVolume.id.in_(select(valid_all_sources.c.volume_id)),
        )
        .values(
            page_count=case(page_counts, value=LibraryVolume.id),
            updated_at=LibraryVolume.updated_at,
        )
    )
    result_statement = (
        update(LibraryFile)
        .where(LibraryFile.id.in_(select(valid_all_sources.c.file_id)))
        .values(
            page_index_version=CURRENT_COMIC_PAGE_INDEX_VERSION,
            updated_at=LibraryFile.updated_at,
        )
    )
    return PreparedComicPageIndexWrite(
        statements=tuple(statements),
        result_statement=result_statement,
    )


class SqlAlchemyComicPageIndexMigrationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(
        self,
        *,
        limit: int,
        after_file_id: str | None,
    ) -> tuple[PendingComicPageIndex, ...]:
        other_file = aliased(LibraryFile)
        first_comic_file_id = (
            select(other_file.id)
            .where(
                other_file.volume_id == LibraryFile.volume_id,
                other_file.kind == "COMIC",
            )
            .order_by(
                other_file.sort_order.asc(),
                other_file.created_at.asc(),
                other_file.id.asc(),
            )
            .limit(1)
            .correlate(LibraryFile)
            .scalar_subquery()
        )
        existing_page_count = (
            select(func.count())
            .select_from(LibraryReadingUnit)
            .where(
                LibraryReadingUnit.volume_id == LibraryFile.volume_id,
                LibraryReadingUnit.unit_type == "page",
            )
            .correlate(LibraryFile)
            .scalar_subquery()
        )
        statement = (
            select(
                LibraryFile.volume_id,
                LibraryFile.id,
                LibraryFile.path,
                LibraryFile.updated_at,
                LibraryFile.size_bytes,
                LibraryFile.mtime_ms,
                LibraryVolume.volume_index,
                LibraryVolume.page_count,
                existing_page_count,
            )
            .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
            .where(
                LibraryFile.kind == "COMIC",
                LibraryFile.page_index_version < CURRENT_COMIC_PAGE_INDEX_VERSION,
                LibraryFile.id == first_comic_file_id,
                LibraryVolume.import_status == "COMPLETED",
            )
            .order_by(LibraryFile.id.asc())
            .limit(limit)
        )
        if after_file_id is not None:
            statement = statement.where(LibraryFile.id > after_file_id)
        return tuple(
            PendingComicPageIndex(
                volume_id=str(row[0]),
                file_id=str(row[1]),
                source_path=str(row[2]),
                source_updated_at=row[3],
                source_size_bytes=int(row[4]),
                source_mtime_ms=int(row[5]),
                volume_index=row[6],
                expected_page_count=row[7],
                existing_page_count=int(row[8]),
            )
            for row in self._session.execute(statement)
        )

    def execute_prepared(self, prepared: PreparedComicPageIndexWrite) -> int:
        for statement in prepared.statements:
            self._session.execute(statement)
        result = self._session.execute(prepared.result_statement)
        return int(result.rowcount or 0)


__all__ = [
    "FileComicPageIndexParser",
    "PreparedComicPageIndexWrite",
    "SqlAlchemyComicPageIndexMigrationRepository",
    "prepare_comic_page_index_write",
]
