"""Import application DTOs shared by queue and media commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IdentitySource = Literal[
    "ai",
    "regex",
    "existing_work",
    "requested",
    "epub_opf",
    "pdf_metadata",
    "comic_info",
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
    monitor_root: Path | None
    audiobook_max_file_bytes: int

    @property
    def resolved_storage_root(self) -> Path:
        return self.storage_root

    @property
    def resolved_monitor_root(self) -> Path | None:
        return self.monitor_root


@dataclass(frozen=True)
class ImportPreferencesDTO:
    auto_convert_to_epub: bool
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
    reused_work_id: str | None = None
    selection_reason: str | None = None
    evidence: tuple[IdentityEvidenceDTO, ...] = ()

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
            "reusedWorkId": self.reused_work_id,
            "selectionReason": self.selection_reason,
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


@dataclass(frozen=True)
class ConversionArtifactDTO:
    source_path: Path
    output_path: Path
    source_format: str
    source_hash: str
    converter: str
    converter_version: str
    cached: bool


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
    monitor_folder_id: str | None = None
    work_id: str | None = None
    edition_id: str | None = None
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
    work_id: str | None = None
    monitor_folder_id: str | None = None
    message: str = "等待后台处理"
    allow_terminal_requeue: bool = False


@dataclass(frozen=True)
class ImportOptions:
    source_file_path: Path
    origin: str
    original_name: str | None = None
    requested_title: str | None = None
    requested_author: str | None = None
    monitor_folder_id: str | None = None
    import_task_id: str | None = None
    original_source_file_path: Path | None = None
    requested_work_id: str | None = None
    expected_lease_owner: str | None = None


@dataclass(frozen=True)
class ImportResult:
    book_id: str
    work_id: str
    edition_id: str
    volume_id: str | None
    title: str
    type: str
    format: str
    total_units: int
    import_status: str
    duplicate: bool
    merged: bool
    merge_reason: str


@dataclass(frozen=True)
class SeriesVolumeInfo:
    series_name: str
    series_index: float
    title: str
    author: str | None = None
