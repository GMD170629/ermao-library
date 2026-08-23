"""Resource-first reader queries and commands."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.reader.application.dto import (
    ExactReaderLocationKind,
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderAudioExactLocationDto,
    ReaderBookmarkDto,
    ReaderBootstrapDto,
    ReaderComicExactLocationDto,
    ReaderExactLocationDto,
    ReaderExternalProgressDto,
    ReaderLocationKind,
    ReaderNavigationUnitDto,
    ReaderPdfExactLocationDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderReflowableExactLocationDto,
    ReaderResourceContextDto,
)
from app.modules.reader.application.exact_location import (
    exact_location_kind,
)
from app.modules.reader.application.ports import (
    ReaderClock,
    ReaderPublicationLocatorIndex,
    ReaderResourceRepository,
    ReaderUnitOfWork,
)
from app.modules.reader.domain.resource_format import (
    ReaderType,
    reader_type_for_format,
)


class ReaderResourceNotFound(Exception):
    pass


class ReaderResourceFormatUnsupported(Exception):
    pass


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
    resource_id: str
    access_scope: ReaderAccessScope
    client_id: str
    mutation_id: str
    base_revision: int
    location: ReaderExactLocationDto
    captured_at_epoch_millis: int


@dataclass(frozen=True, slots=True)
class SetResourceReadingStatusCommand:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    status: ReaderReadingStatus


@dataclass(frozen=True, slots=True)
class ReplaceBookmarksCommand:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    bookmarks: tuple[ReaderBookmarkDto, ...]
    location_kinds: tuple[ReaderLocationKind, ...]


@dataclass(frozen=True, slots=True)
class SaveExternalProgressCommand:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    progression: float
    modified_at: datetime
    device_id: str
    device_name: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReaderProgressDateConflict(Exception):
    current: ReaderExternalProgressDto


class ResourceReaderService:
    def __init__(
        self,
        repository: ReaderResourceRepository,
        unit_of_work: ReaderUnitOfWork,
        clock: ReaderClock,
        publication_locator_index: ReaderPublicationLocatorIndex,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._publication_locator_index = publication_locator_index

    def get_context(self, resource_id: str) -> ReaderResourceContextDto | None:
        return self._repository.get_context(resource_id)

    def load_bootstrap(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderBootstrapDto:
        context = self._repository.get_visible_context(resource_id, access_scope)
        if context is None:
            raise ReaderResourceNotFound
        if reader_type_for_format(context.resource.format) is None:
            raise ReaderResourceFormatUnsupported
        assets = self._repository.list_assets(resource_id)
        units = self._repository.list_navigation_units(resource_id)
        selected_progress = self._repository.get_progress(user_id, resource_id)
        progress_by_resource_id = (
            {resource_id: selected_progress} if selected_progress is not None else {}
        )
        return ReaderBootstrapDto(
            context=context,
            available_resources=(context.resource,),
            assets=tuple(assets),
            units=tuple(units),
            progress_by_resource_id=progress_by_resource_id,
            resume_location_json=(
                selected_progress.location_json
                if selected_progress is not None
                else None
            ),
        )

    def load_progress(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderProgressDto | None:
        context = self._require_visible_context(resource_id, access_scope)
        if reader_type_for_format(context.resource.format) is None:
            raise ReaderResourceFormatUnsupported
        progress = self._repository.get_progress(user_id, resource_id)
        if progress is None or progress.revision < 1 or progress.exact_location is None:
            return None
        return progress

    def save_progress(self, command: SaveProgressCommand) -> ReaderProgressDto:
        context = self._require_visible_context(
            command.resource_id, command.access_scope
        )
        reader_type = reader_type_for_format(context.resource.format)
        if reader_type is None:
            raise ReaderResourceFormatUnsupported
        received_kind = exact_location_kind(command.location)
        if received_kind != reader_type.value:
            raise ReaderLocationFormatMismatch(
                expected=reader_type.value,
                received=received_kind,
            )
        location_is_valid = self._publication_locator_index.validate(
            resource_id=command.resource_id,
            access_scope=command.access_scope,
            location=command.location,
        )
        if not location_is_valid:
            raise ReaderLocatorResourceMismatch(
                href=_location_reference(command.location),
                media_type=reader_type.value,
            )
        now = _aware_utc(self._clock.now())
        progressed_at = datetime.fromtimestamp(
            command.captured_at_epoch_millis / 1000,
            tz=UTC,
        )
        repeated = self._repository.get_progress_mutation(
            command.user_id, command.resource_id, command.mutation_id
        )
        if repeated is not None:
            return repeated
        current = self._repository.get_progress(command.user_id, command.resource_id)
        if current is None and command.base_revision != 0:
            raise ReaderProgressBaseRevisionInvalid
        if current is not None and current.revision != command.base_revision:
            raise ReaderProgressRevisionConflict(current=current)
        next_revision = command.base_revision + 1
        display_percent = _derive_display_percent(
            current=current,
            units=self._repository.list_navigation_units(command.resource_id),
            assets=self._repository.list_assets(command.resource_id),
            page_count=context.resource.page_count,
            location=command.location,
        )
        try:
            progress = self._repository.save_exact_progress(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                display_percent=display_percent,
                location=command.location,
                client_id=command.client_id,
                mutation_id=command.mutation_id,
                base_revision=command.base_revision,
                next_revision=next_revision,
                progressed_at=progressed_at,
                now=now,
            )
            if progress is None:
                repeated = self._repository.get_progress_mutation(
                    command.user_id, command.resource_id, command.mutation_id
                )
                if repeated is not None:
                    self._unit_of_work.rollback()
                    return repeated
                current = self._repository.get_progress(
                    command.user_id, command.resource_id
                )
                if current is None:
                    raise ReaderProgressBaseRevisionInvalid
                raise ReaderProgressRevisionConflict(current=current)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return progress

    def set_resource_reading_status(
        self, command: SetResourceReadingStatusCommand
    ) -> ReaderProgressDto | None:
        if command.status not in {"UNREAD", "FINISHED"}:
            raise ValueError("status must be UNREAD or FINISHED")
        context = self._require_visible_context(
            command.resource_id, command.access_scope
        )
        reader_type = reader_type_for_format(context.resource.format)
        if reader_type is None:
            raise ReaderResourceFormatUnsupported
        try:
            progress = self._repository.set_reading_status(
                user_id=command.user_id,
                context=context,
                reader_type=reader_type.value,
                status=command.status,
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
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderExternalProgressDto | None:
        self._require_visible_context(resource_id, access_scope)
        progress = self._repository.get_progress(user_id, resource_id)
        return _external_progress_dto(progress) if progress is not None else None

    def save_external_progress(
        self, command: SaveExternalProgressCommand
    ) -> ReaderExternalProgressDto:
        if not 0 <= command.progression <= 1:
            raise ValueError("progression must be between zero and one")
        context = self._require_visible_context(
            command.resource_id, command.access_scope
        )
        reader_type = reader_type_for_format(context.resource.format)
        if reader_type is None or reader_type.value == "audio":
            raise ReaderResourceFormatUnsupported
        modified_at = _aware_utc(command.modified_at)
        existing = self._repository.get_progress(command.user_id, command.resource_id)
        if existing is not None and _aware_utc(existing.progressed_at) > modified_at:
            raise ReaderProgressDateConflict(_external_progress_dto(existing))
        location_json = _external_location_json(
            reader_type=reader_type.value,
            resource_id=command.resource_id,
            progression=command.progression,
            page_count=context.resource.page_count,
            references=command.references,
        )
        mutation_source = "\0".join(
            (
                command.user_id,
                command.resource_id,
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
        self, resource_id: str, access_scope: ReaderAccessScope
    ) -> ReaderResourceContextDto:
        context = self._repository.get_visible_context(resource_id, access_scope)
        if context is None:
            raise ReaderResourceNotFound
        return context

    def list_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> list[ReaderBookmarkDto]:
        self._require_visible_context(resource_id, access_scope)
        return self._repository.list_bookmarks(user_id, resource_id)

    def replace_bookmarks(
        self, command: ReplaceBookmarksCommand
    ) -> list[ReaderBookmarkDto]:
        context = self._require_visible_context(
            command.resource_id, command.access_scope
        )
        reader_type = reader_type_for_format(context.resource.format)
        if reader_type is None:
            raise ReaderResourceFormatUnsupported
        for location_kind in command.location_kinds:
            _require_matching_location_kind(reader_type, location_kind)
        try:
            result = self._repository.replace_bookmarks(
                user_id=command.user_id,
                resource_id=command.resource_id,
                bookmarks=list(command.bookmarks),
                now=_aware_utc(self._clock.now()),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result


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
    units: list[ReaderNavigationUnitDto],
    assets: list[ReaderAssetDto],
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
        known_assets = [file for file in assets if file.duration_ms is not None]
        if known_assets and len(known_assets) == len(assets):
            total_duration = sum(file.duration_ms or 0 for file in assets)
            elapsed = 0
            for file in assets:
                if file.id == location.asset_id:
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
    return location.asset_id


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
    resource_id: str,
    progression: float,
    page_count: int | None,
    references: tuple[str, ...],
) -> str:
    if reader_type == "comic":
        location: dict[str, object] = {
            "type": "comic",
            "resourceId": resource_id,
            "pageIndex": _external_page(progression, page_count, references),
        }
    elif reader_type == "pdf":
        location = {
            "type": "pdf",
            "resourceId": resource_id,
            "pageNumber": _external_page(progression, page_count, references),
        }
    else:
        href = next(
            (value for value in references if value and not value.startswith("#")),
            None,
        )
        location = {
            "type": "reflowable",
            "resourceId": resource_id,
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
        resource_id=progress.resource_id,
        progression=max(0, min(1, progress.percent / 100)),
        modified_at=progress.progressed_at,
        device_id=progress.client_id or "urn:shuku:web",
        device_name=progress.source_device_name or "Shuku Web Reader",
        references=_progress_references(progress),
    )
