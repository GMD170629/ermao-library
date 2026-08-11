"""Bounded, restartable maintenance for historical EPUB navigation rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Generic, Protocol, Self, TypeVar

from app.modules.reader.application.dto import ReaderRecoveredEpubChapterDto
from app.modules.reader.application.volume_reader import ReaderEpubNavigationParseError


@dataclass(frozen=True, slots=True)
class PendingEpubNavigation:
    volume_id: str
    file_id: str
    source_path: str
    source_updated_at: datetime


@dataclass(frozen=True, slots=True)
class PreparedEpubNavigation:
    source: PendingEpubNavigation
    chapters: tuple[ReaderRecoveredEpubChapterDto, ...]


NavigationWriteT = TypeVar("NavigationWriteT")


class EpubNavigationMaintenanceRepository(Protocol[NavigationWriteT]):
    def pending(
        self, *, limit: int, after_volume_id: str | None
    ) -> tuple[PendingEpubNavigation, ...]: ...

    def execute_prepared(self, prepared: NavigationWriteT) -> int: ...


class EpubNavigationMaintenanceUnitOfWork(Protocol[NavigationWriteT]):
    navigation: EpubNavigationMaintenanceRepository[NavigationWriteT]

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class EpubNavigationMaintenanceUnitOfWorkFactory(Protocol[NavigationWriteT]):
    def __call__(self) -> EpubNavigationMaintenanceUnitOfWork[NavigationWriteT]: ...


class EpubNavigationMaintenanceParser(Protocol):
    def parse(self, source_path: str) -> tuple[ReaderRecoveredEpubChapterDto, ...]: ...


class EpubNavigationMaintenanceClock(Protocol):
    def __call__(self) -> datetime: ...


class EpubNavigationWritePreparer(Protocol[NavigationWriteT]):
    def __call__(
        self,
        batch: tuple[PreparedEpubNavigation, ...],
        *,
        now: datetime,
    ) -> NavigationWriteT: ...


@dataclass(frozen=True, slots=True)
class EpubNavigationBatchResult:
    scanned: int
    processed: int
    parse_failures: int
    last_volume_id: str | None
    may_have_more: bool


@dataclass(frozen=True, slots=True)
class RebuildEpubNavigationBatch(Generic[NavigationWriteT]):
    unit_of_work_factory: EpubNavigationMaintenanceUnitOfWorkFactory[NavigationWriteT]
    parser: EpubNavigationMaintenanceParser
    clock: EpubNavigationMaintenanceClock
    prepare_write: EpubNavigationWritePreparer[NavigationWriteT]

    def execute(
        self,
        *,
        limit: int = 25,
        after_volume_id: str | None = None,
    ) -> EpubNavigationBatchResult:
        if not 1 <= limit <= 100:
            raise ValueError("EPUB navigation batch limit must be between 1 and 100")
        with self.unit_of_work_factory() as read_unit_of_work:
            pending = read_unit_of_work.navigation.pending(
                limit=limit,
                after_volume_id=after_volume_id,
            )

        prepared: list[PreparedEpubNavigation] = []
        parse_failures = 0
        for source in pending:
            try:
                chapters = self.parser.parse(source.source_path)
            except ReaderEpubNavigationParseError:
                parse_failures += 1
                continue
            if chapters:
                prepared.append(
                    PreparedEpubNavigation(source=source, chapters=chapters)
                )

        processed = 0
        if prepared:
            prepared_write = self.prepare_write(
                tuple(prepared),
                now=self.clock(),
            )
            with self.unit_of_work_factory() as write_unit_of_work:
                processed = write_unit_of_work.navigation.execute_prepared(
                    prepared_write
                )
                write_unit_of_work.commit()
        return EpubNavigationBatchResult(
            scanned=len(pending),
            processed=processed,
            parse_failures=parse_failures,
            last_volume_id=pending[-1].volume_id if pending else None,
            may_have_more=len(pending) == limit,
        )
