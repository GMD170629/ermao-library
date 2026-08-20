"""Filesystem adapter for library-root import discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.application.file_types import is_supported_import_filename
from app.services.audio_metadata import collect_audio_bundle_files
from app.services.import_preferences import (
    DEFAULT_STABILITY_CHECK_ENABLED,
    SUPPORTED_IMPORT_EXTENSIONS,
    ImportPreferences,
    matches_ignore_patterns,
)


@dataclass(frozen=True)
class LibraryConfig:
    id: str
    root_path: str
    organization_mode: str = "FLAT"
    ignore_hidden: bool = True
    ignore_patterns: str | None = None
    min_file_size_bytes: int = 10240
    global_ignore_patterns: str = ""
    allowed_extensions: tuple[str, ...] = SUPPORTED_IMPORT_EXTENSIONS
    stability_check_enabled: bool = DEFAULT_STABILITY_CHECK_ENABLED
    stability_check_seconds: float = 2.0


ImportIgnoreReason = Literal[
    "temporary_upload",
    "hidden_path",
    "global_ignore_pattern",
    "library_ignore_pattern",
    "unsupported_file_type",
    "extension_not_allowed",
    "below_minimum_size",
    "audio_track_limit_exceeded",
]


def library_config(
    row: Any,
    *,
    preferences: ImportPreferences | None = None,
) -> LibraryConfig:
    preferences = preferences or ImportPreferences()
    raw_min_file_size = row.get("minFileSizeBytes")
    return LibraryConfig(
        id=str(row["id"]),
        root_path=str(row["rootPath"]),
        organization_mode=str(row.get("organizationMode") or "FLAT"),
        ignore_hidden=bool(row.get("ignoreHidden", True)),
        ignore_patterns=row.get("ignorePatterns"),
        min_file_size_bytes=int(
            10240 if raw_min_file_size is None else raw_min_file_size
        ),
        global_ignore_patterns=preferences.ignore_patterns,
        allowed_extensions=preferences.allowed_extensions,
        stability_check_enabled=preferences.stability_check_enabled,
        stability_check_seconds=preferences.stability_check_seconds,
    )


def path_ignore_reason(
    path: Path,
    folder: LibraryConfig,
) -> ImportIgnoreReason | None:
    if any(
        part.endswith(".part") or part.startswith(".upload-") for part in path.parts
    ):
        return "temporary_upload"
    if folder.ignore_hidden and any(
        part.startswith(".") and len(part) > 1 for part in path.parts
    ):
        return "hidden_path"
    if matches_ignore_patterns(path, folder.global_ignore_patterns):
        return "global_ignore_pattern"
    if matches_ignore_patterns(path, folder.ignore_patterns):
        return "library_ignore_pattern"
    return None


def should_ignore_path(path: Path, folder: LibraryConfig) -> bool:
    return path_ignore_reason(path, folder) is not None


def import_file_ignore_reason(
    path: Path,
    folder: LibraryConfig,
) -> ImportIgnoreReason | None:
    reason = path_ignore_reason(path, folder)
    if reason is not None:
        return reason
    if not (
        is_supported_import_filename(path)
        or (path.is_dir() and bool(collect_audio_bundle_files(path)))
    ):
        return "unsupported_file_type"
    if path.suffix and path.suffix.lower() not in folder.allowed_extensions:
        return "extension_not_allowed"
    return None


def should_ignore_file(path: Path, folder: LibraryConfig) -> bool:
    return import_file_ignore_reason(path, folder) is not None


def import_source_meets_minimum_size(path: Path, min_file_size_bytes: int) -> bool:
    try:
        if path.is_file():
            return path.stat().st_size >= min_file_size_bytes
        files = collect_audio_bundle_files(path)
        return bool(files) and all(
            item.stat().st_size >= min_file_size_bytes for item in files
        )
    except (AudioTrackLimitExceededError, OSError, ValueError):
        return False


def should_ignore_import_source(path: Path, folder: LibraryConfig) -> bool:
    return import_source_ignore_reason(path, folder) is not None


def import_source_ignore_reason(
    path: Path,
    folder: LibraryConfig,
) -> ImportIgnoreReason | None:
    reason = import_file_ignore_reason(path, folder)
    if reason is not None:
        return reason
    if not import_source_meets_minimum_size(path, folder.min_file_size_bytes):
        return "below_minimum_size"
    return None
