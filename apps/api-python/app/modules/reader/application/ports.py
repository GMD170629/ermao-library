"""Reader application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderBookmarkDto,
    ReaderExactLocationDto,
    ReaderNavigationUnitDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderResourceContextDto,
    ReaderResourceDto,
)


class ReaderResourceRepository(Protocol):
    def get_context(self, resource_id: str) -> ReaderResourceContextDto | None: ...

    def list_visible_resources_for_book(
        self, book_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderResourceDto]: ...

    def list_assets(self, resource_id: str) -> list[ReaderAssetDto]: ...

    def list_navigation_units(
        self, resource_id: str
    ) -> list[ReaderNavigationUnitDto]: ...

    def get_progress(
        self, user_id: str, resource_id: str
    ) -> ReaderProgressDto | None: ...

    def list_progresses(
        self, user_id: str, resource_ids: list[str]
    ) -> list[ReaderProgressDto]: ...

    def get_progress_mutation(
        self, user_id: str, resource_id: str, mutation_id: str
    ) -> ReaderProgressDto | None: ...

    def save_exact_progress(
        self,
        *,
        user_id: str,
        context: ReaderResourceContextDto,
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
        context: ReaderResourceContextDto,
        reader_type: str,
        status: ReaderReadingStatus,
        now: datetime,
    ) -> ReaderProgressDto | None: ...

    def save_external_progress(
        self,
        *,
        user_id: str,
        context: ReaderResourceContextDto,
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
        self, user_id: str, resource_id: str
    ) -> list[ReaderBookmarkDto]: ...

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
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
        resource_id: str,
        access_scope: ReaderAccessScope,
        location: ReaderExactLocationDto,
    ) -> bool: ...
