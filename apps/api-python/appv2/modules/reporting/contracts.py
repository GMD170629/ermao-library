from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LibraryFilterCondition:
    field: str
    operator: str
    value: str | tuple[str, str] | None


@dataclass(frozen=True, slots=True)
class LibraryFilterRules:
    combinator: str
    conditions: tuple[LibraryFilterCondition, ...]


@dataclass(frozen=True, slots=True)
class LibraryQuery:
    page: int
    page_size: int
    query: str | None
    media_type: str | None
    series_name: str | None
    reading_status: str | None
    sort: str
    sort_direction: str
    filters: LibraryFilterRules


@dataclass(frozen=True, slots=True)
class LibraryWorkProjection:
    id: uuid.UUID
    title: str
    author: str | None
    media_type: str
    status: str
    cover_key: str | None
    summary: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryFilterSchema:
    fields: tuple[dict[str, object], ...]
    max_conditions: int


@dataclass(frozen=True, slots=True)
class DashboardProjection:
    work_count: int
    edition_count: int
    active_readers: int
    queued_jobs: int
    continue_item: dict[str, object] | None
    recent_reading: tuple[dict[str, object], ...]
    recent_items: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ManagementProjection:
    users: int
    works: int
    files: int
    queued_imports: int
    queued_downloads: int
    queued_deliveries: int
    failed_jobs: int


class ReportingReadPort(Protocol):
    def library(
        self,
        account_id: uuid.UUID,
        query: LibraryQuery,
    ) -> tuple[list[LibraryWorkProjection], int]: ...

    def library_filter_schema(self, account_id: uuid.UUID) -> LibraryFilterSchema: ...

    def dashboard(self, account_id: uuid.UUID) -> DashboardProjection: ...

    def management(self) -> ManagementProjection: ...
