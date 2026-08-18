"""Import application DTOs shared by queue and media commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.publication_metadata import PublicationMetadata

IdentitySource = Literal[
    "ai",
    "regex",
    "requested",
    "epub_opf",
    "pdf_metadata",
    "comic_info",
    "reflowable_metadata",
    "sidecar_opf",
]


@dataclass(frozen=True)
class IdentityEvidenceDTO:
    source: IdentitySource
    title: str | None
    author: str | None
    confidence: float


@dataclass(frozen=True)
class ImportRuntimeConfig:
    storage_root: Path
    audiobook_max_file_bytes: int

    @property
    def resolved_storage_root(self) -> Path:
        return self.storage_root


@dataclass(frozen=True)
class ImportPreferencesDTO:
    allowed_extensions: tuple[str, ...]
    ignore_patterns: str


@dataclass(frozen=True)
class BookIdentityDTO:
    title: str
    author: str
    volume_index: float | None
    source: IdentitySource
    confidence: float
    logical_path: str
    fallback_reason: str | None = None
    fallback_code: str | None = None
    cache_hit: bool = False
    selection_reason: str | None = None
    evidence: tuple[IdentityEvidenceDTO, ...] = ()
    grouping_kind: Literal[
        "folder", "standalone", "monitor_root_file", "explicit", "legacy"
    ] = "legacy"
    grouping_key: str | None = None

    def raw_metadata(self) -> dict[str, object]:
        return {
            "parserVersion": 5,
            "input": {"logicalPath": self.logical_path},
            "output": {
                "title": self.title,
                "author": self.author,
                "volumeIndex": self.volume_index,
                "confidence": self.confidence,
            },
            "title": self.title,
            "author": self.author,
            "volumeIndex": self.volume_index,
            "source": self.source,
            "confidence": self.confidence,
            "logicalPath": self.logical_path,
            "fallbackReason": self.fallback_reason,
            "fallbackCode": self.fallback_code,
            "cacheHit": self.cache_hit,
            "selectionReason": self.selection_reason,
            "groupingKind": self.grouping_kind,
            "groupingKey": self.grouping_key,
            "evidence": [
                {
                    "source": item.source,
                    "title": item.title,
                    "author": item.author,
                    "confidence": item.confidence,
                }
                for item in self.evidence
            ],
        }


@dataclass(frozen=True, slots=True)
class NonAudioPathResolutionDTO:
    """Complete PATH candidate plus the identity used for grouping."""

    identity: BookIdentityDTO
    metadata: PublicationMetadata


@dataclass(frozen=True)
class DirectorySiblingSnapshotDTO:
    paths: tuple[Path, ...]
    complete: bool


@dataclass(frozen=True)
class ConversionArtifactDTO:
    source_path: Path
    output_path: Path
    source_format: str
    source_key: str
    converter: str
    converter_version: str
    cached: bool
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ConversionProgressTaskDTO:
    """Conversion checkpoint state returned without exposing an ORM entity."""

    id: str
    import_task_id: str
    idempotency_key: str
    status: str
    attempts: int
    started_at: datetime | None


@dataclass(frozen=True)
class ImportSystemEvent:
    source: str
    action: str
    message: str
    level: str = "info"
    actor_type: str = "system"
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ImportTaskDTO:
    id: str
    source_path: str
    origin: str
    status: str
    original_name: str | None = None
    requested_title: str | None = None
    requested_author: str | None = None
    recognized_metadata: Mapping[str, object] | None = None
    library_id: str | None = None
    media_kind_policy: str = "MIXED"
    work_id: str | None = None
    volume_id: str | None = None
    task_kind: str = "FILE"
    bundle_key: str | None = None
    asset_count: int = 1
    processed_asset_count: int = 0
    progress: int = 0
    duplicate: bool = False
    duration: int = 0
    error_summary: str | None = None
    error_code: str | None = None
    retryable: bool = False
    attempts: int = 0
    lease_owner: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class StageImportCommand:
    source_path: Path
    origin: str
    original_name: str | None = None
    requested_title: str | None = None
    requested_author: str | None = None
    library_id: str | None = None
    media_kind_policy: str | None = None
    message: str = "等待后台处理"
    allow_terminal_requeue: bool = False


@dataclass(frozen=True)
class ImportOptions:
    source_file_path: Path
    origin: str
    original_name: str | None = None
    requested_title: str | None = None
    requested_author: str | None = None
    library_id: str | None = None
    media_kind_policy: str = "MIXED"
    import_task_id: str | None = None
    original_source_file_path: Path | None = None
    expected_lease_owner: str | None = None
    default_cover_path: str | None = None
    sidecar_metadata: PublicationMetadata | None = None
    sidecar_cover_path: Path | None = None
    sidecar_source_kind: str | None = None
    path_metadata: PublicationMetadata | None = None
    local_metadata_priority: tuple[LocalMetadataSource, ...] = (
        DEFAULT_LOCAL_METADATA_PRIORITY
    )


@dataclass(frozen=True, slots=True)
class SidecarMetadataDTO:
    metadata: PublicationMetadata
    cover_path: Path | None
    source_kind: str
    field_sources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ImportResult:
    book_id: str
    work_id: str
    media_version_id: str
    volume_id: str | None
    title: str
    type: str
    format: str
    total_units: int
    import_status: str
    duplicate: bool
    merged: bool
    merge_reason: str
    resolved_metadata: PublicationMetadata | None = None
    metadata_field_sources: tuple[tuple[str, str], ...] = ()
    metadata_source_order: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeriesVolumeInfo:
    series_name: str
    series_index: float
    title: str
    author: str | None = None
