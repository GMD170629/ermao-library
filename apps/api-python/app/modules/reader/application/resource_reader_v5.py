"""Reader v5 use cases for opaque progress reports."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderResourceContextDto,
)
from app.modules.reader.application.ports import ReaderClock, ReaderUnitOfWork
from app.modules.reader.application.v5_dto import (
    ReaderV5BookmarkDto,
    ReaderV5BookmarkInputDto,
    ReaderV5BootstrapDto,
    ReaderV5MutationDto,
    ReaderV5PositionDto,
    ReaderV5ProgressDto,
    ReaderV5ReadingStatusDto,
    ReaderV5StoredBookmarkDto,
)
from app.modules.reader.application.v5_ports import ReaderV5Repository
from app.modules.reader.application.v5_position import (
    payload_hash_for_stored,
    serialize_position,
)
from app.modules.reader.domain.resource_format import ReaderType, reader_type_for_format

LOGGER = logging.getLogger(__name__)


class ReaderV5ResourceNotFound(Exception):
    """The resource is absent or outside the actor's visible scope."""


class ReaderV5ResourceFormatUnsupported(Exception):
    """The resource cannot be opened by a Reader client."""


class ReaderV5CapturedAtInvalid(Exception):
    """The client timestamp cannot be represented by the backend clock type."""


@dataclass(frozen=True, slots=True)
class ReaderV5MutationReuse(Exception):
    """A mutation id was reused with a different normalized payload."""

    existing: ReaderV5MutationDto


@dataclass(frozen=True, slots=True)
class SaveProgressV5Command:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    client_id: str
    mutation_id: str
    captured_at_epoch_millis: int
    position: ReaderV5PositionDto

    def __post_init__(self) -> None:
        _validate_client_id(self.client_id)
        _validate_mutation_id(self.mutation_id)
        _validate_epoch_millis(self.captured_at_epoch_millis)


@dataclass(frozen=True, slots=True)
class SetReadingStatusV5Command:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    status: Literal["UNREAD", "FINISHED"]

    def __post_init__(self) -> None:
        if self.status not in {"UNREAD", "FINISHED"}:
            raise ValueError("invalid Reader v5 reading status")


@dataclass(frozen=True, slots=True)
class ReplaceBookmarksV5Command:
    user_id: str
    resource_id: str
    access_scope: ReaderAccessScope
    bookmarks: tuple[ReaderV5BookmarkInputDto, ...]

    def __post_init__(self) -> None:
        if len(self.bookmarks) > 500:
            raise ValueError("Reader v5 supports at most 500 bookmarks")
        bookmark_ids = tuple(bookmark.bookmark_id for bookmark in self.bookmarks)
        if len(bookmark_ids) != len(set(bookmark_ids)):
            raise ValueError("Reader v5 bookmark IDs must be unique")


@dataclass(frozen=True, slots=True)
class SaveProgressV5Result:
    """Accepted receipt plus the snapshot currently visible on the server.

    A replay acknowledges the original mutation revision while returning the
    latest resource snapshot.  Those values can differ when another mutation
    won after the original request.
    """

    accepted_revision: int
    current_progress: ReaderV5ProgressDto


class ResourceReaderV5Service:
    """Application owner of v5 authorization, idempotency, and transactions."""

    def __init__(
        self,
        repository: ReaderV5Repository,
        unit_of_work: ReaderUnitOfWork,
        clock: ReaderClock,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._clock = clock

    def load_bootstrap(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderV5BootstrapDto:
        context = self._require_context(resource_id, access_scope)
        reader_type = reader_type_for_format(context.resource.format)
        if reader_type is None:
            raise ReaderV5ResourceFormatUnsupported
        available_resources = self._repository.list_visible_resources_for_book(
            context.book.id, access_scope
        )
        resource_ids = [resource.id for resource in available_resources]
        progresses = self._repository.list_v5_progresses(user_id, resource_ids)
        progress_by_resource_id = {
            progress.resource_id: progress for progress in progresses
        }
        assets = self._repository.list_assets(resource_id)
        units = (
            []
            if reader_type is ReaderType.REFLOWABLE
            else self._repository.list_navigation_units(resource_id)
        )
        return ReaderV5BootstrapDto(
            context=context,
            available_resources=tuple(available_resources),
            assets=tuple(assets),
            units=tuple(units),
            progress=progress_by_resource_id.get(resource_id),
            progress_by_resource_id=progress_by_resource_id,
        )

    def load_progress(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderV5ProgressDto | None:
        context = self._require_context(resource_id, access_scope)
        if reader_type_for_format(context.resource.format) is None:
            raise ReaderV5ResourceFormatUnsupported
        return self._repository.get_v5_progress(user_id, resource_id)

    def save_progress(self, command: SaveProgressV5Command) -> SaveProgressV5Result:
        self._require_context(command.resource_id, command.access_scope)
        try:
            captured_at = datetime.fromtimestamp(
                command.captured_at_epoch_millis / 1000, tz=UTC
            )
        except (OverflowError, OSError, ValueError) as error:
            LOGGER.warning(
                "reader_v5_progress_rejected",
                extra={
                    "event": "reader_v5_progress_rejected",
                    "outcome": "captured_at_invalid",
                    "resource_id": command.resource_id,
                    "mutation_id": command.mutation_id,
                    "locator_size_bytes": command.position.locator.size_bytes,
                },
            )
            raise ReaderV5CapturedAtInvalid from error
        received_at = _aware_utc(self._clock.now())
        stored_position = serialize_position(command.position)
        request_hash = payload_hash_for_stored(
            client_id=command.client_id,
            mutation_id=command.mutation_id,
            captured_at_epoch_millis=command.captured_at_epoch_millis,
            stored_position=stored_position,
        )
        repeated = self._repository.get_v5_mutation(
            command.user_id, command.resource_id, command.mutation_id
        )
        if repeated is not None:
            if repeated.payload_hash != request_hash:
                LOGGER.warning(
                    "reader_v5_progress_rejected",
                    extra={
                        "event": "reader_v5_progress_rejected",
                        "outcome": "mutation_reuse",
                        "resource_id": command.resource_id,
                        "mutation_id": command.mutation_id,
                        "locator_size_bytes": command.position.locator.size_bytes,
                    },
                )
                raise ReaderV5MutationReuse(existing=repeated)
            current = self._repository.get_v5_progress(
                command.user_id, command.resource_id
            )
            if current is None:
                # The receipt and progress row are committed atomically.  A
                # missing current row indicates storage corruption rather than
                # a valid idempotent replay.
                raise RuntimeError("Reader v5 mutation receipt has no progress row")
            LOGGER.info(
                "reader_v5_progress_accepted",
                extra={
                    "event": "reader_v5_progress_accepted",
                    "outcome": "idempotent_replay",
                    "resource_id": command.resource_id,
                    "mutation_id": command.mutation_id,
                    "accepted_revision": repeated.accepted_revision,
                    "current_revision": current.revision,
                    "locator_size_bytes": command.position.locator.size_bytes,
                },
            )
            return SaveProgressV5Result(
                accepted_revision=repeated.accepted_revision,
                current_progress=current,
            )
        try:
            progress = self._repository.save_v5_progress(
                user_id=command.user_id,
                resource_id=command.resource_id,
                client_id=command.client_id,
                mutation_id=command.mutation_id,
                payload_hash=request_hash,
                stored_position=stored_position,
                captured_at=captured_at,
                received_at=received_at,
            )
            self._unit_of_work.commit()
        except Exception as error:
            self._unit_of_work.rollback()
            if not self._repository.is_mutation_conflict(error):
                LOGGER.exception(
                    "reader_v5_progress_failed",
                    extra={
                        "event": "reader_v5_progress_failed",
                        "outcome": "storage_failure",
                        "resource_id": command.resource_id,
                        "mutation_id": command.mutation_id,
                        "locator_size_bytes": command.position.locator.size_bytes,
                    },
                )
                raise
            repeated = self._repository.get_v5_mutation(
                command.user_id, command.resource_id, command.mutation_id
            )
            if repeated is not None:
                if repeated.payload_hash != request_hash:
                    LOGGER.warning(
                        "reader_v5_progress_rejected",
                        extra={
                            "event": "reader_v5_progress_rejected",
                            "outcome": "mutation_reuse",
                            "resource_id": command.resource_id,
                            "mutation_id": command.mutation_id,
                            "locator_size_bytes": command.position.locator.size_bytes,
                        },
                    )
                    raise ReaderV5MutationReuse(existing=repeated) from error
                current = self._repository.get_v5_progress(
                    command.user_id, command.resource_id
                )
                if current is None:
                    raise RuntimeError(
                        "Reader v5 mutation receipt has no progress row"
                    ) from error
                LOGGER.info(
                    "reader_v5_progress_accepted",
                    extra={
                        "event": "reader_v5_progress_accepted",
                        "outcome": "idempotent_race_replay",
                        "resource_id": command.resource_id,
                        "mutation_id": command.mutation_id,
                        "accepted_revision": repeated.accepted_revision,
                        "current_revision": current.revision,
                        "locator_size_bytes": command.position.locator.size_bytes,
                    },
                )
                return SaveProgressV5Result(
                    accepted_revision=repeated.accepted_revision,
                    current_progress=current,
                )
            LOGGER.exception(
                "reader_v5_progress_failed",
                extra={
                    "event": "reader_v5_progress_failed",
                    "outcome": "mutation_conflict_without_receipt",
                    "resource_id": command.resource_id,
                    "mutation_id": command.mutation_id,
                    "locator_size_bytes": command.position.locator.size_bytes,
                },
            )
            raise
        LOGGER.info(
            "reader_v5_progress_accepted",
            extra={
                "event": "reader_v5_progress_accepted",
                "outcome": "accepted",
                "resource_id": command.resource_id,
                "mutation_id": command.mutation_id,
                "accepted_revision": progress.revision,
                "current_revision": progress.revision,
                "locator_size_bytes": command.position.locator.size_bytes,
            },
        )
        return SaveProgressV5Result(
            accepted_revision=progress.revision,
            current_progress=progress,
        )

    def get_reading_status(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderV5ReadingStatusDto | None:
        self._require_context(resource_id, access_scope)
        return self._repository.get_v5_reading_status(user_id, resource_id)

    def set_reading_status(
        self, command: SetReadingStatusV5Command
    ) -> ReaderV5ReadingStatusDto:
        self._require_context(command.resource_id, command.access_scope)
        try:
            status = self._repository.set_v5_reading_status(
                user_id=command.user_id,
                resource_id=command.resource_id,
                status=command.status,
                updated_at=_aware_utc(self._clock.now()),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return status

    def load_bookmarks(
        self,
        *,
        user_id: str,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> list[ReaderV5BookmarkDto]:
        self._require_context(resource_id, access_scope)
        return self._repository.list_v5_bookmarks(user_id, resource_id)

    def replace_bookmarks(
        self, command: ReplaceBookmarksV5Command
    ) -> list[ReaderV5BookmarkDto]:
        self._require_context(command.resource_id, command.access_scope)
        stored = tuple(
            ReaderV5StoredBookmarkDto(
                bookmark_id=bookmark.bookmark_id,
                stored_position=serialize_position(bookmark.position),
                label=bookmark.label,
                created_at=_aware_utc(bookmark.created_at),
            )
            for bookmark in command.bookmarks
        )
        try:
            bookmarks = self._repository.replace_v5_bookmarks(
                user_id=command.user_id,
                resource_id=command.resource_id,
                bookmarks=stored,
                updated_at=_aware_utc(self._clock.now()),
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return bookmarks

    def _require_context(
        self, resource_id: str, access_scope: ReaderAccessScope
    ) -> ReaderResourceContextDto:
        context = self._repository.get_visible_context(resource_id, access_scope)
        if context is None:
            raise ReaderV5ResourceNotFound
        return context


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_client_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(
            "client_id must be a non-blank string of at most 256 characters"
        )


def _validate_mutation_id(value: str) -> None:
    try:
        UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("mutation_id must be a UUID") from error


def _validate_epoch_millis(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("captured_at_epoch_millis must be a non-negative integer")
