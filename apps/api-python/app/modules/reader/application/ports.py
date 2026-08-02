"""Reader application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderFileDto,
    ReaderProgressDto,
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

    def save_progress(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        percent: float,
        location_json: str,
        content_fingerprint: str,
        mutation_id: str,
        client_id: str,
        client_sequence: int,
        now: datetime,
    ) -> ReaderProgressDto: ...

    def list_bookmarks(
        self, user_id: str, volume_id: str, content_fingerprint: str
    ) -> list[ReaderBookmarkDto]: ...

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        volume_id: str,
        content_fingerprint: str,
        bookmarks: list[ReaderBookmarkDto],
        now: datetime,
    ) -> list[ReaderBookmarkDto]: ...


class ReaderUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...
