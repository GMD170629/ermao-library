"""Reader application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderExactLocationDto,
    ReaderFileDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderUnitDto,
    ReaderVolumeContextDto,
    ReaderVolumeDto,
)


class ReaderVolumeRepository(Protocol):
    def get_context(self, volume_id: str) -> ReaderVolumeContextDto | None: ...

    def list_visible_volumes_for_work(
        self, work_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderVolumeDto]: ...

    def list_files(self, volume_id: str) -> list[ReaderFileDto]: ...

    def list_units(self, volume_id: str) -> list[ReaderUnitDto]: ...

    def get_progress(
        self, user_id: str, volume_id: str
    ) -> ReaderProgressDto | None: ...

    def list_progresses(
        self, user_id: str, volume_ids: list[str]
    ) -> list[ReaderProgressDto]: ...

    def get_progress_mutation(
        self, user_id: str, volume_id: str, mutation_id: str
    ) -> ReaderProgressDto | None: ...

    def save_exact_progress(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        display_percent: float,
        location: ReaderExactLocationDto,
        client_id: str,
        mutation_id: str,
        base_revision: int,
        next_revision: int,
        progressed_at: datetime,
        now: datetime,
    ) -> ReaderProgressDto | None: ...

    def set_reading_status(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        status: ReaderReadingStatus,
        now: datetime,
    ) -> ReaderProgressDto | None: ...

    def save_external_progress(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        percent: float,
        location_json: str,
        mutation_id: str,
        client_id: str,
        client_sequence: int,
        progressed_at: datetime,
        source_protocol: str,
        source_device_name: str,
        now: datetime,
    ) -> ReaderProgressDto: ...

    def list_bookmarks(
        self, user_id: str, volume_id: str
    ) -> list[ReaderBookmarkDto]: ...

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        volume_id: str,
        bookmarks: list[ReaderBookmarkDto],
        now: datetime,
    ) -> list[ReaderBookmarkDto]: ...


class ReaderUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ReaderClock(Protocol):
    def now(self) -> datetime: ...


class ReaderPublicationLocatorIndex(Protocol):
    def validate(
        self,
        *,
        volume_id: str,
        access_scope: ReaderAccessScope,
        location: ReaderExactLocationDto,
    ) -> bool: ...
