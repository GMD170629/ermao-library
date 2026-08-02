"""Volume-first reader queries and commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.modules.reader.application.content_fingerprint import (
    build_volume_content_fingerprint,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderBootstrapDto,
    ReaderProgressDto,
    ReaderVolumeContextDto,
)
from app.modules.reader.application.ports import (
    ReaderUnitOfWork,
    ReaderVolumeRepository,
)
from app.modules.reader.domain.volume_format import reader_type_for_volume_format


class ReaderVolumeNotFound(Exception):
    pass


class ReaderVolumeFormatUnsupported(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReaderFingerprintMismatch(Exception):
    expected: str
    received: str


@dataclass(frozen=True, slots=True)
class SaveProgressCommand:
    user_id: str
    volume_id: str
    mutation_id: str
    client_id: str
    client_sequence: int
    content_fingerprint: str
    location_json: str
    percent: float


@dataclass(frozen=True, slots=True)
class SaveProgressResult:
    applied: bool
    progress: ReaderProgressDto


class VolumeReaderService:
    def __init__(
        self,
        repository: ReaderVolumeRepository,
        unit_of_work: ReaderUnitOfWork,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work

    def get_context(self, volume_id: str) -> ReaderVolumeContextDto | None:
        return self._repository.get_context(volume_id)

    def load_bootstrap(
        self,
        *,
        user_id: str,
        volume_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderBootstrapDto:
        context = self._repository.get_context(volume_id)
        if context is None:
            raise ReaderVolumeNotFound
        if reader_type_for_volume_format(context.volume.format) is None:
            raise ReaderVolumeFormatUnsupported
        available_volumes = self._repository.list_visible_volumes_for_work(
            context.work.id, access_scope
        )
        if all(volume.id != volume_id for volume in available_volumes):
            raise ReaderVolumeNotFound
        files = self._repository.list_files(volume_id)
        units = self._repository.list_units(volume_id)
        progresses = self._repository.list_progresses(
            user_id, [volume.id for volume in available_volumes]
        )
        progress_by_volume_id = {
            progress.volume_id: progress for progress in progresses
        }
        fingerprint = build_volume_content_fingerprint(
            asdict(context.volume), [asdict(file) for file in files]
        )
        selected_progress = progress_by_volume_id.get(volume_id)
        fingerprint_mismatch = bool(
            selected_progress
            and selected_progress.content_fingerprint
            and selected_progress.content_fingerprint != fingerprint
        )
        selected_media_volumes = [
            volume
            for volume in available_volumes
            if volume.media_version_id == context.media_version.id
        ]
        media_completed = bool(selected_media_volumes) and all(
            progress_by_volume_id.get(volume.id) is not None
            and progress_by_volume_id[volume.id].percent >= 100
            for volume in selected_media_volumes
        )
        return ReaderBootstrapDto(
            context=context,
            available_volumes=tuple(available_volumes),
            files=tuple(files),
            units=tuple(units),
            progress_by_volume_id=progress_by_volume_id,
            content_fingerprint=fingerprint,
            resume_location_json=(
                None
                if fingerprint_mismatch or selected_progress is None
                else selected_progress.location_json
            ),
            resume_fingerprint_mismatch=fingerprint_mismatch,
            media_completed=media_completed,
        )

    def save_progress(self, command: SaveProgressCommand) -> SaveProgressResult:
        context = self._repository.get_context(command.volume_id)
        if context is None:
            raise ReaderVolumeNotFound
        reader_type = reader_type_for_volume_format(context.volume.format)
        if reader_type is None:
            raise ReaderVolumeFormatUnsupported
        expected_fingerprint = build_volume_content_fingerprint(
            asdict(context.volume),
            [asdict(file) for file in self._repository.list_files(command.volume_id)],
        )
        if command.content_fingerprint != expected_fingerprint:
            raise ReaderFingerprintMismatch(
                expected=expected_fingerprint,
                received=command.content_fingerprint,
            )
        existing = self._repository.get_progress(command.user_id, command.volume_id)
        if existing and (
            existing.mutation_id == command.mutation_id
            or (
                existing.client_id == command.client_id
                and (existing.client_sequence or -1) >= command.client_sequence
            )
        ):
            return SaveProgressResult(applied=False, progress=existing)
        try:
            progress = self._repository.save_progress(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                percent=command.percent,
                location_json=command.location_json,
                content_fingerprint=expected_fingerprint,
                mutation_id=command.mutation_id,
                client_id=command.client_id,
                client_sequence=command.client_sequence,
                now=datetime.now(UTC),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return SaveProgressResult(applied=True, progress=progress)

    def list_bookmarks(
        self,
        *,
        user_id: str,
        volume_id: str,
        content_fingerprint: str,
    ) -> list[ReaderBookmarkDto]:
        self._require_current_fingerprint(volume_id, content_fingerprint)
        return self._repository.list_bookmarks(user_id, volume_id, content_fingerprint)

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        volume_id: str,
        content_fingerprint: str,
        bookmarks: list[ReaderBookmarkDto],
    ) -> list[ReaderBookmarkDto]:
        self._require_current_fingerprint(volume_id, content_fingerprint)
        try:
            result = self._repository.replace_bookmarks(
                user_id=user_id,
                volume_id=volume_id,
                content_fingerprint=content_fingerprint,
                bookmarks=bookmarks,
                now=datetime.now(UTC),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result

    def _require_current_fingerprint(
        self, volume_id: str, received_fingerprint: str
    ) -> None:
        context = self._repository.get_context(volume_id)
        if context is None:
            raise ReaderVolumeNotFound
        expected = build_volume_content_fingerprint(
            asdict(context.volume),
            [asdict(file) for file in self._repository.list_files(volume_id)],
        )
        if expected != received_fingerprint:
            raise ReaderFingerprintMismatch(
                expected=expected,
                received=received_fingerprint,
            )
