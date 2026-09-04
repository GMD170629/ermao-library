"""Application ports for Reader v5 progress persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderNavigationUnitDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)
from app.modules.reader.application.v5_dto import (
    ReaderV5BookmarkDto,
    ReaderV5MutationDto,
    ReaderV5ProgressDto,
    ReaderV5ReadingStatusDto,
    ReaderV5StoredBookmarkDto,
)
from app.modules.reader.application.v5_position import ReaderV5StoredPosition


class ReaderV5Repository(Protocol):
    def is_mutation_conflict(self, error: Exception) -> bool: ...

    def get_visible_context(
        self, resource_id: str, access_scope: ReaderAccessScope
    ) -> ReaderResourceContextDto | None: ...

    def list_visible_resources_for_book(
        self, book_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderResourceDto]: ...

    def list_assets(self, resource_id: str) -> list[ReaderAssetDto]: ...

    def list_navigation_units(
        self, resource_id: str
    ) -> list[ReaderNavigationUnitDto]: ...

    def get_v5_progress(
        self, user_id: str, resource_id: str
    ) -> ReaderV5ProgressDto | None: ...

    def list_v5_progresses(
        self, user_id: str, resource_ids: list[str]
    ) -> list[ReaderV5ProgressDto]: ...

    def get_v5_mutation(
        self, user_id: str, resource_id: str, mutation_id: str
    ) -> ReaderV5MutationDto | None: ...

    def save_v5_progress(
        self,
        *,
        user_id: str,
        resource_id: str,
        client_id: str,
        mutation_id: str,
        payload_hash: str,
        stored_position: ReaderV5StoredPosition,
        captured_at: datetime,
        received_at: datetime,
    ) -> ReaderV5ProgressDto: ...

    def get_v5_reading_status(
        self, user_id: str, resource_id: str
    ) -> ReaderV5ReadingStatusDto | None: ...

    def set_v5_reading_status(
        self,
        *,
        user_id: str,
        resource_id: str,
        status: Literal["UNREAD", "FINISHED"],
        updated_at: datetime,
    ) -> ReaderV5ReadingStatusDto: ...

    def list_v5_bookmarks(
        self, user_id: str, resource_id: str
    ) -> list[ReaderV5BookmarkDto]: ...

    def replace_v5_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
        bookmarks: tuple[ReaderV5StoredBookmarkDto, ...],
        updated_at: datetime,
    ) -> list[ReaderV5BookmarkDto]: ...
