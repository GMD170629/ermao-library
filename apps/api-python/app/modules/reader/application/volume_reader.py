"""Volume-first reader queries and commands."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.modules.reader.application.content_fingerprint import (
    build_publication_fingerprint,
    build_volume_content_fingerprint,
    publication_fingerprint_key,
)
from app.modules.reader.application.dto import (
    ExactReaderLocationKind,
    ReaderAccessScope,
    ReaderAudioExactLocationDto,
    ReaderBookmarkDto,
    ReaderBootstrapDto,
    ReaderComicExactLocationDto,
    ReaderExactLocationDto,
    ReaderExternalProgressDto,
    ReaderFileDto,
    ReaderLocationKind,
    ReaderPdfExactLocationDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderReflowableExactLocationDto,
    ReaderUnitDto,
    ReaderVolumeContextDto,
)
from app.modules.reader.application.exact_location import (
    exact_location_kind,
    exact_location_publication,
)
from app.modules.reader.application.ports import (
    ReaderClock,
    ReaderEpubNavigationParser,
    ReaderPublicationLocatorIndex,
    ReaderUnitOfWork,
    ReaderVolumeRepository,
)
from app.modules.reader.domain.volume_format import (
    ReaderType,
    reader_type_for_volume_format,
)
from app.contracts.media_capabilities import capability_for_format

_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[a-fA-F0-9]{64}$")


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
class ReaderLocationFormatMismatch(Exception):
    expected: ReaderLocationKind | ExactReaderLocationKind
    received: ReaderLocationKind | ExactReaderLocationKind


@dataclass(frozen=True, slots=True)
class ReaderLocatorMediaTypeMismatch(Exception):
    expected: str
    received: str


@dataclass(frozen=True, slots=True)
class ReaderLocatorResourceMismatch(Exception):
    href: str
    media_type: str


@dataclass(frozen=True, slots=True)
class ReaderProgressRevisionConflict(Exception):
    current: ReaderProgressDto


class ReaderProgressBaseRevisionInvalid(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SaveProgressCommand:
    user_id: str
    volume_id: str
    access_scope: ReaderAccessScope
    client_id: str
    mutation_id: str
    base_revision: int
    location: ReaderExactLocationDto
    captured_at_epoch_millis: int


@dataclass(frozen=True, slots=True)
class SetVolumeReadingStatusCommand:
    user_id: str
    volume_id: str
    access_scope: ReaderAccessScope
    status: ReaderReadingStatus


@dataclass(frozen=True, slots=True)
class ReplaceBookmarksCommand:
    user_id: str
    volume_id: str
    access_scope: ReaderAccessScope
    content_fingerprint: str
    bookmarks: tuple[ReaderBookmarkDto, ...]
    location_kinds: tuple[ReaderLocationKind, ...]


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
        clock: ReaderClock,
        publication_locator_index: ReaderPublicationLocatorIndex,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._epub_navigation_parser = epub_navigation_parser
        self._clock = clock
        self._publication_locator_index = publication_locator_index

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
        capability = capability_for_format(context.volume.format)
        if capability is None or (
            capability.requires_full_hash
            and (
                len(files) != 1
                or files[0].full_hash is None
                or _SHA256_PATTERN.fullmatch(files[0].full_hash) is None
            )
        ):
            # Exact cross-platform restoration is unsafe until preparation has
            # established the immutable source identity.
            raise ReaderVolumeFormatUnsupported
        units = self._repository.list_units(volume_id)
        progresses = self._repository.list_progresses(
            user_id, [volume.id for volume in available_volumes]
        )
        progress_by_volume_id = {
            progress.volume_id: progress for progress in progresses
        }
        publication_fingerprint = self._publication_locator_index.fingerprint(
            volume_id=volume_id,
            access_scope=access_scope,
        ) or build_publication_fingerprint(
            asdict(context.volume), [asdict(file) for file in files]
        )
        fingerprint_key = publication_fingerprint_key(publication_fingerprint)
        selected_progress = progress_by_volume_id.get(volume_id)
        fingerprint_mismatch = bool(
            selected_progress
            and selected_progress.content_fingerprint
            and selected_progress.content_fingerprint != fingerprint_key
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
            publication_fingerprint=publication_fingerprint,
            resume_location_json=(
                None
                if fingerprint_mismatch or selected_progress is None
                else selected_progress.location_json
            ),
            media_completed=media_completed,
        )

    def save_progress(self, command: SaveProgressCommand) -> ReaderProgressDto:
        context = self._require_visible_context(command.volume_id, command.access_scope)
        reader_type = reader_type_for_volume_format(context.volume.format)
        if reader_type is None:
            raise ReaderVolumeFormatUnsupported
        received_kind = exact_location_kind(command.location)
        if received_kind != reader_type.value:
            raise ReaderLocationFormatMismatch(
                expected=reader_type.value,
                received=received_kind,
            )
        expected_publication = self._publication_locator_index.validate(
            volume_id=command.volume_id,
            access_scope=command.access_scope,
            location=command.location,
        )
        if expected_publication is None:
            raise ReaderLocatorResourceMismatch(
                href=_location_reference(command.location),
                media_type=reader_type.value,
            )
        received = exact_location_publication(command.location)
        received_publication = (
            received.original_file_hash.lower(),
            received.parser,
            received.normalization,
        )
        expected_identity = (
            expected_publication.original_file_hash.lower(),
            expected_publication.parser,
            expected_publication.normalization,
        )
        if received_publication != expected_identity:
            raise ReaderFingerprintMismatch(
                expected=publication_fingerprint_key(expected_publication),
                received="|".join(received_publication),
            )
        fingerprint_key = publication_fingerprint_key(expected_publication)
        now = _aware_utc(self._clock.now())
        progressed_at = datetime.fromtimestamp(
            command.captured_at_epoch_millis / 1000,
            tz=UTC,
        )
        repeated = self._repository.get_progress_mutation(
            command.user_id, command.volume_id, command.mutation_id
        )
        if repeated is not None:
            return repeated
        current = self._repository.get_progress(command.user_id, command.volume_id)
        if current is None and command.base_revision != 0:
            raise ReaderProgressBaseRevisionInvalid
        if current is not None and current.revision != command.base_revision:
            raise ReaderProgressRevisionConflict(current=current)
        next_revision = command.base_revision + 1
        display_percent = _derive_display_percent(
            current=current,
            units=self._repository.list_units(command.volume_id),
            files=self._repository.list_files(command.volume_id),
            page_count=context.volume.page_count,
            location=command.location,
        )
        try:
            progress = self._repository.save_exact_progress(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                display_percent=display_percent,
                location=command.location,
                content_fingerprint=fingerprint_key,
                client_id=command.client_id,
                mutation_id=command.mutation_id,
                base_revision=command.base_revision,
                next_revision=next_revision,
                progressed_at=progressed_at,
                now=now,
            )
            if progress is None:
                repeated = self._repository.get_progress_mutation(
                    command.user_id, command.volume_id, command.mutation_id
                )
                if repeated is not None:
                    self._unit_of_work.rollback()
                    return repeated
                current = self._repository.get_progress(
                    command.user_id, command.volume_id
                )
                if current is None:
                    raise ReaderProgressBaseRevisionInvalid
                raise ReaderProgressRevisionConflict(current=current)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return progress

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
                now=_aware_utc(self._clock.now()),
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
        now = _aware_utc(self._clock.now())
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
        access_scope: ReaderAccessScope,
        content_fingerprint: str,
    ) -> list[ReaderBookmarkDto]:
        self._require_current_fingerprint(
            volume_id,
            content_fingerprint,
            access_scope=access_scope,
        )
        return self._repository.list_bookmarks(user_id, volume_id, content_fingerprint)

    def replace_bookmarks(
        self, command: ReplaceBookmarksCommand
    ) -> list[ReaderBookmarkDto]:
        context = self._require_visible_context(command.volume_id, command.access_scope)
        reader_type = reader_type_for_volume_format(context.volume.format)
        if reader_type is None:
            raise ReaderVolumeFormatUnsupported
        for location_kind in command.location_kinds:
            _require_matching_location_kind(reader_type, location_kind)
        self._require_current_fingerprint(
            command.volume_id,
            command.content_fingerprint,
            access_scope=command.access_scope,
        )
        try:
            result = self._repository.replace_bookmarks(
                user_id=command.user_id,
                volume_id=command.volume_id,
                content_fingerprint=command.content_fingerprint,
                bookmarks=list(command.bookmarks),
                now=_aware_utc(self._clock.now()),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result

    def _require_current_fingerprint(
        self,
        volume_id: str,
        received_fingerprint: str,
        *,
        access_scope: ReaderAccessScope,
    ) -> None:
        context = self._repository.get_context(volume_id)
        if context is None:
            raise ReaderVolumeNotFound
        publication = self._publication_locator_index.fingerprint(
            volume_id=volume_id,
            access_scope=access_scope,
        )
        expected = (
            f"{publication.original_file_hash}\0{publication.parser}"
            f"\0{publication.normalization}"
            if publication is not None
            else build_volume_content_fingerprint(
                asdict(context.volume),
                [asdict(file) for file in self._repository.list_files(volume_id)],
            )
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


def _require_matching_location_kind(
    reader_type: ReaderType,
    location_kind: ReaderLocationKind | None,
) -> None:
    if location_kind is None:
        return
    expected_by_reader_type: dict[ReaderType, ReaderLocationKind] = {
        ReaderType.REFLOWABLE: "reflow",
        ReaderType.COMIC: "comic",
        ReaderType.PDF: "pdf",
        ReaderType.AUDIO: "audio",
    }
    expected = expected_by_reader_type[reader_type]
    if location_kind != expected:
        raise ReaderLocationFormatMismatch(expected=expected, received=location_kind)


def _require_matching_locator_media_type(
    reader_type: ReaderType, media_type: str
) -> None:
    normalized = media_type.partition(";")[0].strip().lower()
    accepted_prefixes: dict[ReaderType, tuple[str, ...]] = {
        ReaderType.REFLOWABLE: (
            "application/xhtml+xml",
            "text/html",
            "text/plain",
        ),
        ReaderType.COMIC: ("image/",),
        ReaderType.PDF: ("application/pdf",),
        ReaderType.AUDIO: ("audio/",),
    }
    if any(normalized.startswith(prefix) for prefix in accepted_prefixes[reader_type]):
        return
    raise ReaderLocatorMediaTypeMismatch(
        expected=reader_type.value,
        received=media_type,
    )


def _derive_display_percent(
    *,
    current: ReaderProgressDto | None,
    units: list[ReaderUnitDto],
    files: list[ReaderFileDto],
    page_count: int | None,
    location: ReaderExactLocationDto,
) -> float:
    """Derive a presentation-only percentage without affecting restoration."""

    if isinstance(location, ReaderReflowableExactLocationDto):
        if location.total_progression is not None:
            return round(location.total_progression * 100, 6)
        normalized_href = location.resource_href.partition("#")[0]
        for index, unit in enumerate(units):
            if unit.href.partition("#")[0] == normalized_href and units:
                within_resource = location.resource_progression or 0
                return round((index + within_resource) / len(units) * 100, 6)
        if location.resource_progression is not None:
            return round(location.resource_progression * 100, 6)
    elif isinstance(location, ReaderPdfExactLocationDto) and page_count:
        return round(
            min(1.0, (location.page_index + location.page_progression) / page_count)
            * 100,
            6,
        )
    elif isinstance(location, ReaderComicExactLocationDto) and page_count:
        if page_count == 1:
            return 100
        return round(location.page_index / (page_count - 1) * 100, 6)
    elif isinstance(location, ReaderAudioExactLocationDto):
        known_files = [file for file in files if file.duration_ms is not None]
        if known_files and len(known_files) == len(files):
            total_duration = sum(file.duration_ms or 0 for file in files)
            elapsed = 0
            for file in files:
                if file.id == location.file_id:
                    elapsed += location.position_millis
                    break
                elapsed += file.duration_ms or 0
            if total_duration > 0:
                return round(min(1.0, elapsed / total_duration) * 100, 6)
    if current is not None:
        return current.percent
    return 0


def _location_reference(location: ReaderExactLocationDto) -> str:
    if isinstance(location, ReaderReflowableExactLocationDto):
        return location.resource_href
    if isinstance(location, ReaderPdfExactLocationDto):
        return f"page-{location.page_index + 1}"
    if isinstance(location, ReaderComicExactLocationDto):
        return location.resource_href
    return location.file_id


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
