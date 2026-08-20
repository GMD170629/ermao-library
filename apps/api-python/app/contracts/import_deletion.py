"""Stable cross-capability contract for one prepared volume deletion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreparedLibraryVolumeDeletion:
    volume_id: str
    version_id: str
    work_id: str
    cover_path: str | None
    file_ids: tuple[str, ...]
    file_paths: tuple[str, ...]
    delete_version: bool
    delete_work: bool


@dataclass(frozen=True, slots=True)
class LibraryVolumeDeletionResult:
    deleted: bool
    deleted_work: bool
    work_id: str
