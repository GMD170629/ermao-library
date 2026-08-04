"""Application use case for downloading an explicit volume selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.authorization import AuthorizationContext


@dataclass(frozen=True, slots=True)
class VolumeArchiveSource:
    volume_id: str
    volume_title: str
    source_path: str


@dataclass(frozen=True, slots=True)
class VolumeArchiveSelection:
    work_title: str
    sources: tuple[VolumeArchiveSource, ...]


@dataclass(frozen=True, slots=True)
class PreparedVolumeArchive:
    path: str
    download_name: str


class VolumeArchiveRepository(Protocol):
    def get_volume_archive_selection(
        self,
        *,
        actor: AuthorizationContext,
        work_id: str,
        volume_ids: tuple[str, ...],
    ) -> VolumeArchiveSelection | None: ...


class VolumeArchiveWriter(Protocol):
    def create(self, selection: VolumeArchiveSelection) -> PreparedVolumeArchive: ...


class InvalidVolumeArchiveSelectionError(Exception):
    pass


class VolumeArchiveSourceMissingError(Exception):
    pass


def prepare_volume_archive(
    repository: VolumeArchiveRepository,
    writer: VolumeArchiveWriter,
    *,
    actor: AuthorizationContext,
    work_id: str,
    volume_ids: tuple[str, ...],
) -> PreparedVolumeArchive:
    if not volume_ids:
        raise InvalidVolumeArchiveSelectionError("VOLUME_SELECTION_REQUIRED")
    if len(set(volume_ids)) != len(volume_ids):
        raise InvalidVolumeArchiveSelectionError("DUPLICATE_VOLUME_IDS")
    selection = repository.get_volume_archive_selection(
        actor=actor,
        work_id=work_id,
        volume_ids=volume_ids,
    )
    if selection is None or len(selection.sources) != len(volume_ids):
        raise InvalidVolumeArchiveSelectionError("VOLUME_NOT_FOUND")
    if any(not source.source_path for source in selection.sources):
        raise VolumeArchiveSourceMissingError("VOLUME_SOURCE_MISSING")
    return writer.create(selection)
