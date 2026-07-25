from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.modules.catalog.contracts import CatalogFile
from appv2.platform.database.contracts import UnitOfWork
from appv2.platform.http.ranges import ByteRange


@dataclass(frozen=True, slots=True)
class ReaderTarget:
    work_id: uuid.UUID
    work_title: str
    work_author: str | None
    edition_id: uuid.UUID
    edition_title: str
    file_id: uuid.UUID
    format: str
    media_type: str
    resource_url: str
    checksum: str


@dataclass(frozen=True, slots=True)
class ProgressMutation:
    edition_id: uuid.UUID
    user_id: uuid.UUID
    device_id: str
    position: dict[str, object]
    percentage: float
    occurred_at: datetime
    expected_version: int | None = None


@dataclass(frozen=True, slots=True)
class ProgressView:
    edition_id: uuid.UUID
    user_id: uuid.UUID
    position: dict[str, object]
    percentage: float
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BulkProgressSkipped:
    work_id: uuid.UUID
    reason: str


@dataclass(frozen=True, slots=True)
class BulkProgressResult:
    updated: int
    changed_values: int
    skipped: tuple[BulkProgressSkipped, ...] = ()


@dataclass(frozen=True, slots=True)
class BookmarkView:
    id: uuid.UUID
    edition_id: uuid.UUID
    client_id: str
    label: str | None
    position: dict[str, object]
    excerpt: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PreferenceView:
    scope: str
    target_id: uuid.UUID | None
    values: dict[str, object]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LocationCacheView:
    edition_id: uuid.UUID
    content_fingerprint: str
    cache_version: int
    break_size: int
    serialized: str | None
    owner: str
    token_hash: str
    expires_at: datetime


class ReadingRepository(Protocol):
    def get_progress(self, *, user_id: uuid.UUID, edition_id: uuid.UUID) -> ProgressView | None: ...

    def save_progress(self, mutation: ProgressMutation) -> ProgressView: ...

    def delete_progress(
        self,
        *,
        user_id: uuid.UUID,
        edition_ids: list[uuid.UUID],
    ) -> int: ...

    def list_bookmarks(
        self, *, user_id: uuid.UUID, edition_id: uuid.UUID
    ) -> list[BookmarkView]: ...

    def put_bookmark(
        self,
        *,
        user_id: uuid.UUID,
        edition_id: uuid.UUID,
        client_id: str,
        label: str | None,
        position: dict[str, object],
        excerpt: str | None,
    ) -> BookmarkView: ...

    def delete_bookmark(
        self, *, user_id: uuid.UUID, edition_id: uuid.UUID, bookmark_id: uuid.UUID
    ) -> bool: ...

    def get_preference(
        self, *, user_id: uuid.UUID, scope: str, target_id: uuid.UUID | None
    ) -> PreferenceView | None: ...

    def save_preference(
        self,
        *,
        user_id: uuid.UUID,
        scope: str,
        target_id: uuid.UUID | None,
        values: dict[str, object],
    ) -> PreferenceView: ...

    def claim_locations(
        self,
        *,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
        owner: str,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> LocationCacheView: ...

    def save_locations(
        self,
        *,
        edition_id: uuid.UUID,
        content_fingerprint: str,
        cache_version: int,
        break_size: int,
        token_hash: str,
        serialized: str,
        now: datetime,
    ) -> LocationCacheView: ...


class ReadingUnitOfWork(UnitOfWork, Protocol):
    reading: ReadingRepository


@dataclass(frozen=True, slots=True)
class ResourceStream:
    body: Iterable[bytes]
    media_type: str
    status_code: int
    content_length: int
    content_range: str | None
    etag: str
    last_modified: str
    filename: str


@dataclass(frozen=True, slots=True)
class ComicPage:
    page_index: int
    title: str
    media_type: str
    size_bytes: int


class ReaderResourcePort(Protocol):
    def open(
        self,
        file: CatalogFile,
        *,
        requested_range: ByteRange | None,
        stream_key: str,
    ) -> ResourceStream: ...

    def comic_pages(self, file: CatalogFile) -> list[ComicPage]: ...

    def open_comic_page(
        self,
        file: CatalogFile,
        *,
        page_index: int,
        stream_key: str,
    ) -> ResourceStream: ...
