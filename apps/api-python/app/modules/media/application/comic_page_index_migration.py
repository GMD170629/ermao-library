"""Restartable data migration for persistent comic page indexes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Generic, Protocol, Self, TypeVar


class ComicPageIndexParseError(RuntimeError):
    """A comic source could not be inspected during the startup migration."""


@dataclass(frozen=True, slots=True)
class PendingComicPageIndex:
    volume_id: str
    file_id: str
    source_path: str
    source_updated_at: datetime
    source_size_bytes: int
    source_mtime_ms: int
    volume_index: float | None
    expected_page_count: int | None
    existing_page_count: int


@dataclass(frozen=True, slots=True)
class ComicPageIndexPage:
    index: int
    title: str
    entry_path: str
    media_type: str
    size: int


@dataclass(frozen=True, slots=True)
class PreparedComicPageIndex:
    source: PendingComicPageIndex
    pages: tuple[ComicPageIndexPage, ...]
    reuse_existing: bool = False

    @property
    def page_count(self) -> int:
        return (
            self.source.existing_page_count
            if self.reuse_existing
            else len(self.pages)
        )


ComicPageIndexWriteT = TypeVar("ComicPageIndexWriteT")


class ComicPageIndexMigrationRepository(Protocol[ComicPageIndexWriteT]):
    def pending(
        self, *, limit: int, after_file_id: str | None
    ) -> tuple[PendingComicPageIndex, ...]: ...

    def execute_prepared(self, prepared: ComicPageIndexWriteT) -> int: ...


class ComicPageIndexMigrationUnitOfWork(Protocol[ComicPageIndexWriteT]):
    page_indexes: ComicPageIndexMigrationRepository[ComicPageIndexWriteT]

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class ComicPageIndexMigrationUnitOfWorkFactory(Protocol[ComicPageIndexWriteT]):
    def __call__(self) -> ComicPageIndexMigrationUnitOfWork[ComicPageIndexWriteT]: ...


class ComicPageIndexParser(Protocol):
    def parse(
        self, source: PendingComicPageIndex
    ) -> tuple[ComicPageIndexPage, ...]: ...


class ComicPageIndexClock(Protocol):
    def __call__(self) -> datetime: ...


class ComicPageIndexWritePreparer(Protocol[ComicPageIndexWriteT]):
    def __call__(
        self,
        batch: tuple[PreparedComicPageIndex, ...],
        *,
        now: datetime,
    ) -> ComicPageIndexWriteT: ...


@dataclass(frozen=True, slots=True)
class ComicPageIndexMigrationBatchResult:
    scanned: int
    processed: int
    inserted_page_rows: int
    failed_file_ids: tuple[str, ...]
    last_file_id: str | None
    may_have_more: bool


def _can_reuse_existing_index(source: PendingComicPageIndex) -> bool:
    return source.existing_page_count > 0 and source.expected_page_count in {
        None,
        source.existing_page_count,
    }


@dataclass(frozen=True, slots=True)
class MigrateComicPageIndexBatch(Generic[ComicPageIndexWriteT]):
    unit_of_work_factory: ComicPageIndexMigrationUnitOfWorkFactory[
        ComicPageIndexWriteT
    ]
    parser: ComicPageIndexParser
    clock: ComicPageIndexClock
    prepare_write: ComicPageIndexWritePreparer[ComicPageIndexWriteT]

    def execute(
        self,
        *,
        limit: int = 25,
        max_page_rows: int = 750,
        after_file_id: str | None = None,
    ) -> ComicPageIndexMigrationBatchResult:
        if not 1 <= limit <= 100:
            raise ValueError("comic page-index batch limit must be between 1 and 100")
        if max_page_rows < 1:
            raise ValueError("comic page-index row budget must be positive")

        with self.unit_of_work_factory() as read_unit_of_work:
            pending = read_unit_of_work.page_indexes.pending(
                limit=limit,
                after_file_id=after_file_id,
            )

        prepared: list[PreparedComicPageIndex] = []
        failed_file_ids: list[str] = []
        inserted_page_rows = 0
        scanned = 0
        last_file_id: str | None = None
        stopped_for_row_budget = False
        for source in pending:
            if _can_reuse_existing_index(source):
                candidate = PreparedComicPageIndex(
                    source=source,
                    pages=(),
                    reuse_existing=True,
                )
            else:
                if (
                    prepared
                    and source.expected_page_count is not None
                    and inserted_page_rows + source.expected_page_count
                    > max_page_rows
                ):
                    stopped_for_row_budget = True
                    break
                try:
                    pages = self.parser.parse(source)
                except ComicPageIndexParseError:
                    failed_file_ids.append(source.file_id)
                    scanned += 1
                    last_file_id = source.file_id
                    continue
                if not pages:
                    failed_file_ids.append(source.file_id)
                    scanned += 1
                    last_file_id = source.file_id
                    continue
                if prepared and inserted_page_rows + len(pages) > max_page_rows:
                    stopped_for_row_budget = True
                    break
                candidate = PreparedComicPageIndex(source=source, pages=pages)
                inserted_page_rows += len(pages)
            prepared.append(candidate)
            scanned += 1
            last_file_id = source.file_id

        processed = 0
        if prepared:
            prepared_write = self.prepare_write(
                tuple(prepared),
                now=self.clock(),
            )
            with self.unit_of_work_factory() as write_unit_of_work:
                processed = write_unit_of_work.page_indexes.execute_prepared(
                    prepared_write
                )
                write_unit_of_work.commit()

        return ComicPageIndexMigrationBatchResult(
            scanned=scanned,
            processed=processed,
            inserted_page_rows=inserted_page_rows,
            failed_file_ids=tuple(failed_file_ids),
            last_file_id=last_file_id,
            may_have_more=stopped_for_row_budget or len(pending) == limit,
        )


__all__ = [
    "ComicPageIndexMigrationBatchResult",
    "ComicPageIndexPage",
    "ComicPageIndexParseError",
    "MigrateComicPageIndexBatch",
    "PendingComicPageIndex",
    "PreparedComicPageIndex",
]
