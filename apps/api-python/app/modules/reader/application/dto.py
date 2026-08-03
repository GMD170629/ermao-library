"""Explicit application DTOs for the volume-first reader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReaderAccessScope:
    is_admin: bool
    can_view_manual_imports: bool
    monitor_folder_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderWorkDto:
    id: str
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class ReaderMediaVersionDto:
    id: str
    work_id: str
    media_kind: str


@dataclass(frozen=True, slots=True)
class ReaderVolumeDto:
    id: str
    media_version_id: str
    title: str
    volume_index: float | None
    sort_order: int
    format: str
    derived_from_volume_id: str | None
    page_count: int | None
    chapter_count: int | None
    duration_ms: int | None
    track_count: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderFileDto:
    id: str
    volume_id: str
    kind: str
    mime_type: str
    size_bytes: int
    duration_ms: int | None
    disc_number: int | None
    track_number: int | None
    sort_order: int
    fingerprint: str | None
    full_hash: str | None
    mtime_ms: int
    codec: str | None = None


@dataclass(frozen=True, slots=True)
class ReaderEpubSourceDto:
    file_id: str
    path: str


@dataclass(frozen=True, slots=True)
class ReaderRecoveredEpubChapterDto:
    title: str
    href: str
    sort_order: int
    idref: str | None
    media_type: str | None


@dataclass(frozen=True, slots=True)
class ReaderUnitDto:
    id: str
    volume_id: str
    file_id: str | None
    unit_type: str
    title: str
    href: str
    sort_order: int
    start_ms: int | None
    end_ms: int | None
    duration_ms: int | None
    metadata_json: str


@dataclass(frozen=True, slots=True)
class ReaderProgressDto:
    id: str
    user_id: str
    volume_id: str
    reader_type: str
    percent: float
    location_json: str | None
    content_fingerprint: str | None
    mutation_id: str | None
    client_id: str | None
    client_sequence: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderBookmarkDto:
    id: str
    bookmark_id: str
    location_json: str
    label: str
    percent: float
    bookmark_created_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderVolumeContextDto:
    work: ReaderWorkDto
    media_version: ReaderMediaVersionDto
    volume: ReaderVolumeDto


@dataclass(frozen=True, slots=True)
class ReaderBootstrapDto:
    context: ReaderVolumeContextDto
    available_volumes: tuple[ReaderVolumeDto, ...]
    files: tuple[ReaderFileDto, ...]
    units: tuple[ReaderUnitDto, ...]
    progress_by_volume_id: dict[str, ReaderProgressDto]
    content_fingerprint: str
    resume_location_json: str | None
    resume_fingerprint_mismatch: bool
    media_completed: bool
