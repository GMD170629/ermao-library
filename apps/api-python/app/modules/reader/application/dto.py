"""Explicit application DTOs for the resource-first reader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ReaderReadingStatus = Literal["UNREAD", "FINISHED"]
ReaderLocationKind = Literal["reflow", "comic", "pdf", "audio"]
ExactReaderLocationKind = Literal["reflowable", "comic", "pdf", "audio"]


@dataclass(frozen=True, slots=True)
class ReaderAccessScope:
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderBookDto:
    id: str
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class ReaderResourceDto:
    id: str
    book_id: str
    source_node_id: str
    title: str
    media_kind: str
    format: str
    resource_index: float | None
    sort_order: int
    page_count: int | None
    chapter_count: int | None
    duration_ms: int | None
    track_count: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderAssetDto:
    id: str
    resource_id: str
    source_node_id: str
    role: str
    mime_type: str
    size_bytes: int
    duration_ms: int | None
    disc_number: int | None
    track_number: int | None
    sort_order: int
    mtime_ms: int
    codec: str | None = None


@dataclass(frozen=True, slots=True)
class ReaderNavigationUnitDto:
    id: str
    resource_id: str
    asset_id: str | None
    unit_type: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    start_ms: int | None
    end_ms: int | None
    duration_ms: int | None
    metadata_json: str


@dataclass(frozen=True, slots=True)
class ReaderEngineLocatorDto:
    platform: Literal["android", "ios", "web"]
    version: str
    payload_json: str


@dataclass(frozen=True, slots=True)
class ReaderReflowableExactLocationDto:
    resource_href: str
    media_type: str
    resource_progression: float | None
    total_progression: float | None
    engine_locator: ReaderEngineLocatorDto


@dataclass(frozen=True, slots=True)
class ReaderPdfExactLocationDto:
    page_index: int
    page_progression: float
    engine_locator: ReaderEngineLocatorDto | None = None


@dataclass(frozen=True, slots=True)
class ReaderComicExactLocationDto:
    page_index: int
    resource_href: str
    engine_locator: ReaderEngineLocatorDto | None = None


@dataclass(frozen=True, slots=True)
class ReaderAudioExactLocationDto:
    asset_id: str
    chapter_id: str | None
    position_millis: int
    engine_locator: ReaderEngineLocatorDto | None = None


ReaderExactLocationDto = (
    ReaderReflowableExactLocationDto
    | ReaderPdfExactLocationDto
    | ReaderComicExactLocationDto
    | ReaderAudioExactLocationDto
)


@dataclass(frozen=True, slots=True)
class ReaderProgressDto:
    id: str
    user_id: str
    resource_id: str
    reader_type: str
    percent: float
    location_json: str | None
    exact_location: ReaderExactLocationDto | None
    mutation_id: str | None
    client_id: str | None
    client_sequence: int | None
    progressed_at: datetime
    source_protocol: str
    source_device_name: str | None
    updated_at: datetime
    revision: int


@dataclass(frozen=True, slots=True)
class ReaderExternalProgressDto:
    resource_id: str
    progression: float
    modified_at: datetime
    device_id: str
    device_name: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderBookmarkDto:
    id: str
    bookmark_id: str
    location_json: str
    label: str
    percent: float
    bookmark_created_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderResourceContextDto:
    book: ReaderBookDto
    resource: ReaderResourceDto


@dataclass(frozen=True, slots=True)
class ReaderBootstrapDto:
    context: ReaderResourceContextDto
    available_resources: tuple[ReaderResourceDto, ...]
    assets: tuple[ReaderAssetDto, ...]
    units: tuple[ReaderNavigationUnitDto, ...]
    progress_by_resource_id: dict[str, ReaderProgressDto]
    resume_location_json: str | None
