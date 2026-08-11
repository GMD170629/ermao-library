"""Volume-first reader queries and commands."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.modules.reader.application.content_fingerprint import (
    build_volume_content_fingerprint,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderBootstrapDto,
    ReaderExternalProgressDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderVolumeContextDto,
)
from app.modules.reader.application.ports import (
    ReaderEpubNavigationParser,
    ReaderUnitOfWork,
    ReaderVolumeRepository,
)
from app.modules.reader.domain.volume_format import reader_type_for_volume_format


class ReaderVolumeNotFound(Exception):
    pass


class ReaderVolumeFormatUnsupported(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReaderEpubNavigationParseError(Exception):
    source_path: str


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


@dataclass(frozen=True, slots=True)
class SetVolumeReadingStatusCommand:
    user_id: str
    volume_id: str
    access_scope: ReaderAccessScope
    status: ReaderReadingStatus


@dataclass(frozen=True, slots=True)
class SaveExternalProgressCommand:
    user_id: str
    volume_id: str
    access_scope: ReaderAccessScope
    progression: float
    modified_at: datetime
    device_id: str
    device_name: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderProgressDateConflict(Exception):
    current: ReaderExternalProgressDto


class VolumeReaderService:
    def __init__(
        self,
        repository: ReaderVolumeRepository,
        unit_of_work: ReaderUnitOfWork,
        epub_navigation_parser: ReaderEpubNavigationParser,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._epub_navigation_parser = epub_navigation_parser

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
        try:
            progress, applied = self._repository.save_progress(
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
        return SaveProgressResult(applied=applied, progress=progress)

    def set_volume_reading_status(
        self, command: SetVolumeReadingStatusCommand
    ) -> ReaderProgressDto | None:
        if command.status not in {"UNREAD", "FINISHED"}:
            raise ValueError("status must be UNREAD or FINISHED")
        context = self._require_visible_context(command.volume_id, command.access_scope)
        reader_type = reader_type_for_volume_format(context.volume.format)
        if reader_type is None:
            raise ReaderVolumeFormatUnsupported
        fingerprint = build_volume_content_fingerprint(
            asdict(context.volume),
            [asdict(file) for file in self._repository.list_files(command.volume_id)],
        )
        try:
            progress = self._repository.set_reading_status(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                status=command.status,
                content_fingerprint=fingerprint,
                now=datetime.now(UTC),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return progress

    def get_external_progress(
        self,
        *,
        user_id: str,
        volume_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderExternalProgressDto | None:
        self._require_visible_context(volume_id, access_scope)
        progress = self._repository.get_progress(user_id, volume_id)
        return _external_progress_dto(progress) if progress is not None else None

    def save_external_progress(
        self, command: SaveExternalProgressCommand
    ) -> ReaderExternalProgressDto:
        if not 0 <= command.progression <= 1:
            raise ValueError("progression must be between zero and one")
        context = self._require_visible_context(command.volume_id, command.access_scope)
        reader_type = reader_type_for_volume_format(context.volume.format)
        if reader_type is None or reader_type.value == "audio":
            raise ReaderVolumeFormatUnsupported
        modified_at = _aware_utc(command.modified_at)
        existing = self._repository.get_progress(command.user_id, command.volume_id)
        if existing is not None and _aware_utc(existing.progressed_at) > modified_at:
            raise ReaderProgressDateConflict(_external_progress_dto(existing))
        files = self._repository.list_files(command.volume_id)
        fingerprint = build_volume_content_fingerprint(
            asdict(context.volume), [asdict(file) for file in files]
        )
        location_json = _external_location_json(
            reader_type=reader_type.value,
            volume_id=command.volume_id,
            progression=command.progression,
            page_count=context.volume.page_count,
            references=command.references,
        )
        mutation_source = "\0".join(
            (
                command.user_id,
                command.volume_id,
                command.device_id,
                modified_at.isoformat(),
                f"{command.progression:.12f}",
                *command.references,
            )
        )
        mutation_id = (
            "opds-" + hashlib.sha256(mutation_source.encode("utf-8")).hexdigest()[:48]
        )
        now = datetime.now(UTC)
        try:
            progress = self._repository.save_external_progress(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                percent=command.progression * 100,
                location_json=location_json,
                content_fingerprint=fingerprint,
                mutation_id=mutation_id,
                client_id=command.device_id,
                client_sequence=int(modified_at.timestamp() * 1000),
                progressed_at=modified_at,
                source_protocol="OPDS_PROGRESSION_1",
                source_device_name=command.device_name,
                now=now,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return _external_progress_dto(progress)

    def _require_visible_context(
        self, volume_id: str, access_scope: ReaderAccessScope
    ) -> ReaderVolumeContextDto:
        context = self._repository.get_context(volume_id)
        if context is None:
            raise ReaderVolumeNotFound
        visible = self._repository.list_visible_volumes_for_work(
            context.work.id, access_scope
        )
        if all(volume.id != volume_id for volume in visible):
            raise ReaderVolumeNotFound
        return context

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


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _page_from_references(references: tuple[str, ...]) -> int | None:
    for reference in references:
        marker = reference.rpartition("#page=")[2]
        if marker.isdigit():
            page = int(marker)
            if page >= 1:
                return page
    return None


def _external_page(
    progression: float,
    page_count: int | None,
    references: tuple[str, ...],
) -> int:
    referenced = _page_from_references(references)
    if page_count and referenced is not None:
        return min(page_count, referenced)
    if not page_count or page_count <= 1:
        return 1
    return min(
        page_count,
        max(1, int(progression * (page_count - 1) + 0.5) + 1),
    )


def _external_location_json(
    *,
    reader_type: str,
    volume_id: str,
    progression: float,
    page_count: int | None,
    references: tuple[str, ...],
) -> str:
    if reader_type == "comic":
        location: dict[str, object] = {
            "type": "comic",
            "volumeId": volume_id,
            "pageIndex": _external_page(progression, page_count, references),
        }
    elif reader_type == "pdf":
        location = {
            "type": "pdf",
            "volumeId": volume_id,
            "pageNumber": _external_page(progression, page_count, references),
        }
    else:
        href = next(
            (value for value in references if value and not value.startswith("#")),
            None,
        )
        location = {
            "type": "reflowable",
            "volumeId": volume_id,
            "format": "epub",
            "progression": progression,
        }
        if href is not None:
            location["href"] = href
    return json.dumps(location, ensure_ascii=False, separators=(",", ":"))


def _progress_references(progress: ReaderProgressDto) -> tuple[str, ...]:
    if not progress.location_json:
        return ()
    try:
        location: object = json.loads(progress.location_json)
    except json.JSONDecodeError:
        return ()
    if not isinstance(location, dict):
        return ()
    location_type = location.get("type")
    if location_type == "comic":
        page = location.get("pageIndex")
        return (f"#page={page}",) if isinstance(page, int) and page >= 1 else ()
    if location_type == "pdf":
        page = location.get("pageNumber")
        return (f"#page={page}",) if isinstance(page, int) and page >= 1 else ()
    href = location.get("href")
    return (href,) if isinstance(href, str) and href else ()


def _external_progress_dto(progress: ReaderProgressDto) -> ReaderExternalProgressDto:
    return ReaderExternalProgressDto(
        volume_id=progress.volume_id,
        progression=max(0, min(1, progress.percent / 100)),
        modified_at=progress.progressed_at,
        device_id=progress.client_id or "urn:shuku:web",
        device_name=progress.source_device_name or "Shuku Web Reader",
        references=_progress_references(progress),
    )
