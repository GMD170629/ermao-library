"""Apply explicitly selected metadata-provider values to a Book target."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, NotRequired, Protocol, TypedDict

from app.modules.library.application.resource_commands import LibraryActor

LOGGER = logging.getLogger(__name__)


class MetadataTargetScope(StrEnum):
    BOOK = "book"
    RESOURCE = "resource"


class RecognizedMetadataField(StrEnum):
    BOOK_TITLE = "book.title"
    BOOK_AUTHOR = "book.author"
    BOOK_DESCRIPTION = "book.description"
    BOOK_SERIES_NAME = "book.seriesName"
    BOOK_SERIES_INDEX = "book.seriesIndex"
    BOOK_TAGS = "book.tags"
    BOOK_COVER = "book.cover"
    RESOURCE_TITLE = "resource.title"
    RESOURCE_DESCRIPTION = "resource.description"
    RESOURCE_PUBLISHER = "resource.publisher"
    RESOURCE_PUBLISHED_AT = "resource.publishedAt"
    RESOURCE_LANGUAGE = "resource.language"
    RESOURCE_ISBN = "resource.isbn"
    RESOURCE_IDENTIFIER = "resource.identifier"
    RESOURCE_NARRATOR = "resource.narrator"
    RESOURCE_ABRIDGED = "resource.abridged"
    RESOURCE_INDEX = "resource.resourceIndex"
    RESOURCE_COVER = "resource.cover"


BOOK_SCOPE_FIELDS = frozenset(
    {
        RecognizedMetadataField.BOOK_TITLE,
        RecognizedMetadataField.BOOK_AUTHOR,
        RecognizedMetadataField.BOOK_DESCRIPTION,
        RecognizedMetadataField.BOOK_SERIES_NAME,
        RecognizedMetadataField.BOOK_SERIES_INDEX,
        RecognizedMetadataField.BOOK_TAGS,
        RecognizedMetadataField.BOOK_COVER,
    }
)
RESOURCE_SCOPE_FIELDS = frozenset(
    {
        RecognizedMetadataField.BOOK_AUTHOR,
        RecognizedMetadataField.BOOK_SERIES_NAME,
        RecognizedMetadataField.BOOK_SERIES_INDEX,
        RecognizedMetadataField.BOOK_TAGS,
        RecognizedMetadataField.RESOURCE_TITLE,
        RecognizedMetadataField.RESOURCE_DESCRIPTION,
        RecognizedMetadataField.RESOURCE_PUBLISHER,
        RecognizedMetadataField.RESOURCE_PUBLISHED_AT,
        RecognizedMetadataField.RESOURCE_LANGUAGE,
        RecognizedMetadataField.RESOURCE_ISBN,
        RecognizedMetadataField.RESOURCE_IDENTIFIER,
        RecognizedMetadataField.RESOURCE_NARRATOR,
        RecognizedMetadataField.RESOURCE_ABRIDGED,
        RecognizedMetadataField.RESOURCE_INDEX,
        RecognizedMetadataField.RESOURCE_COVER,
    }
)


@dataclass(frozen=True, slots=True)
class RecognizedMetadataCandidate:
    id: str
    source: str
    title: str | None = None
    author: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    series_name: str | None = None
    series_index: float | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    isbn: str | None = None
    identifier: str | None = None
    narrator: str | None = None
    abridged: bool | None = None
    resource_index: float | None = None
    cover_url: str | None = None


@dataclass(frozen=True, slots=True)
class BookMetadataState:
    title: str
    author: str | None
    description: str | None
    series_name: str | None
    series_index: float | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceMetadataState:
    title: str
    description: str | None
    publisher: str | None
    published_at: datetime | None
    language: str | None
    isbn: str | None
    identifier: str | None
    narrator: str | None
    abridged: bool | None
    resource_index: float | None


@dataclass(frozen=True, slots=True)
class RecognizedMetadataTargetState:
    book: BookMetadataState
    resource: ResourceMetadataState | None


class BookMetadataChanges(TypedDict, total=False):
    title: NotRequired[str]
    author: NotRequired[str | None]
    description: NotRequired[str | None]
    series_name: NotRequired[str | None]
    series_index: NotRequired[float | None]


class RecognizedResourceChanges(TypedDict, total=False):
    title: NotRequired[str]
    description: NotRequired[str | None]
    publisher: NotRequired[str | None]
    published_at: NotRequired[datetime | None]
    language: NotRequired[str | None]
    isbn: NotRequired[str | None]
    identifier: NotRequired[str | None]
    narrator: NotRequired[str | None]
    abridged: NotRequired[bool | None]
    resource_index: NotRequired[float | None]


class RecognizedMetadataPort(Protocol):
    def load_target(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
    ) -> RecognizedMetadataTargetState | None: ...

    def apply_changes(
        self,
        *,
        book_id: str,
        resource_id: str | None,
        book_changes: BookMetadataChanges,
        resource_changes: RecognizedResourceChanges,
        tags: tuple[str, ...] | None,
        now: datetime,
    ) -> None: ...


class RecognizedMetadataUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class RecognizedCoverApplication(Protocol):
    def apply(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
        cover_url: str,
        now: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RecognizedCoverState:
    target_id: str
    current_cover_path: str | None


@dataclass(frozen=True, slots=True)
class PublishedRecognizedCover:
    target_id: str
    stored_path: str
    final_path: Path
    backup_path: Path | None


class RecognizedCoverMetadataPort(Protocol):
    def load_cover_state(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
    ) -> RecognizedCoverState | None: ...

    def mark_cover_ready(
        self,
        *,
        state: RecognizedCoverState,
        scope: MetadataTargetScope,
        cover_path: str,
        now: datetime,
    ) -> None: ...


class RemoteCoverDownloadPort(Protocol):
    def download(self, cover_url: str) -> bytes: ...


class RecognizedCoverPublicationPort(Protocol):
    def publish(
        self,
        *,
        scope: MetadataTargetScope,
        target_id: str,
        content: bytes,
        previous_stored_path: str | None,
    ) -> PublishedRecognizedCover: ...

    def revert(self, published: PublishedRecognizedCover) -> None: ...

    def complete(
        self,
        published: PublishedRecognizedCover,
        *,
        previous_stored_path: str | None,
    ) -> None: ...


class ApplyRecognizedCover:
    """Download and atomically publish one explicitly selected remote cover."""

    def __init__(
        self,
        metadata: RecognizedCoverMetadataPort,
        downloader: RemoteCoverDownloadPort,
        publication: RecognizedCoverPublicationPort,
        unit_of_work: RecognizedMetadataUnitOfWork,
    ) -> None:
        self._metadata = metadata
        self._downloader = downloader
        self._publication = publication
        self._unit_of_work = unit_of_work

    def apply(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_id: str | None,
        scope: MetadataTargetScope,
        cover_url: str,
        now: datetime,
    ) -> None:
        state = self._metadata.load_cover_state(
            actor=actor,
            book_id=book_id,
            resource_id=resource_id,
            scope=scope,
        )
        if state is None:
            self._unit_of_work.rollback()
            raise RecognizedMetadataTargetNotFoundError
        # End the read transaction before DNS, TLS, and remote I/O.
        self._unit_of_work.rollback()
        content = self._downloader.download(cover_url)
        published = self._publication.publish(
            scope=scope,
            target_id=state.target_id,
            content=content,
            previous_stored_path=state.current_cover_path,
        )
        try:
            self._metadata.mark_cover_ready(
                state=state,
                scope=scope,
                cover_path=published.stored_path,
                now=now,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            self._publication.revert(published)
            raise
        self._publication.complete(
            published,
            previous_stored_path=state.current_cover_path,
        )


@dataclass(frozen=True, slots=True)
class ApplyRecognizedMetadataCommand:
    actor: LibraryActor
    book_id: str
    scope: MetadataTargetScope
    resource_id: str | None
    candidate: RecognizedMetadataCandidate
    fields: tuple[RecognizedMetadataField, ...]
    now: datetime


@dataclass(frozen=True, slots=True)
class ApplyRecognizedMetadataResult:
    applied_fields: tuple[RecognizedMetadataField, ...]
    skipped_fields: tuple[RecognizedMetadataField, ...]
    cover_status: Literal["notSelected", "applied", "failed"]


class RecognizedMetadataAuthorizationError(Exception):
    pass


class RecognizedMetadataTargetNotFoundError(Exception):
    pass


class InvalidRecognizedMetadataError(ValueError):
    pass


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\t\r\f\v ]+", " ", value).strip()
    return normalized or None


def _tags(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value)
        key = (normalized or "").casefold()
        if normalized is None or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _number(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        raise InvalidRecognizedMetadataError("metadata number must be finite")
    return float(value)


def _required_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRecognizedMetadataError("metadata number is unavailable")
    return float(value)


def _same(left: object, right: object) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return _text(str(left) if left is not None else None) == _text(
            str(right) if right is not None else None
        )
    return left == right


class ApplyRecognizedMetadata:
    def __init__(
        self,
        port: RecognizedMetadataPort,
        unit_of_work: RecognizedMetadataUnitOfWork,
        covers: RecognizedCoverApplication,
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work
        self._covers = covers

    def execute(
        self, command: ApplyRecognizedMetadataCommand
    ) -> ApplyRecognizedMetadataResult:
        if not command.actor.can_manage_system:
            raise RecognizedMetadataAuthorizationError
        if not command.fields or len(set(command.fields)) != len(command.fields):
            raise InvalidRecognizedMetadataError(
                "metadata fields are empty or repeated"
            )
        allowed = (
            BOOK_SCOPE_FIELDS
            if command.scope is MetadataTargetScope.BOOK
            else RESOURCE_SCOPE_FIELDS
        )
        if set(command.fields) - allowed:
            raise InvalidRecognizedMetadataError("metadata field does not match target")
        if (
            command.scope is MetadataTargetScope.BOOK
            and command.resource_id is not None
        ):
            raise InvalidRecognizedMetadataError(
                "book target cannot include resourceId"
            )
        if command.scope is MetadataTargetScope.RESOURCE and not command.resource_id:
            raise InvalidRecognizedMetadataError("resource target requires resourceId")

        state = self._port.load_target(
            actor=command.actor,
            book_id=command.book_id,
            resource_id=command.resource_id,
        )
        if state is None or (
            command.scope is MetadataTargetScope.RESOURCE and state.resource is None
        ):
            self._unit_of_work.rollback()
            raise RecognizedMetadataTargetNotFoundError

        book_changes: BookMetadataChanges = {}
        resource_changes: RecognizedResourceChanges = {}
        next_tags: tuple[str, ...] | None = None
        applied: list[RecognizedMetadataField] = []
        skipped: list[RecognizedMetadataField] = []
        cover_field: RecognizedMetadataField | None = None

        try:
            for field in command.fields:
                if field in {
                    RecognizedMetadataField.BOOK_COVER,
                    RecognizedMetadataField.RESOURCE_COVER,
                }:
                    if _text(command.candidate.cover_url) is None:
                        raise InvalidRecognizedMetadataError(
                            "selected cover is unavailable"
                        )
                    cover_field = field
                    continue
                current, value = self._field_values(field, state, command.candidate)
                if value is None or value == ():
                    raise InvalidRecognizedMetadataError(
                        "selected metadata value is unavailable"
                    )
                if _same(current, value):
                    skipped.append(field)
                    continue
                self._assign(field, value, book_changes, resource_changes)
                if field is RecognizedMetadataField.BOOK_TAGS:
                    next_tags = value if isinstance(value, tuple) else None
                applied.append(field)
        except Exception:
            self._unit_of_work.rollback()
            raise

        if book_changes or resource_changes or next_tags is not None:
            try:
                self._port.apply_changes(
                    book_id=command.book_id,
                    resource_id=command.resource_id,
                    book_changes=book_changes,
                    resource_changes=resource_changes,
                    tags=next_tags,
                    now=command.now,
                )
                self._unit_of_work.commit()
            except Exception:
                self._unit_of_work.rollback()
                raise
        else:
            self._unit_of_work.rollback()

        cover_status: Literal["notSelected", "applied", "failed"] = "notSelected"
        if cover_field is not None:
            try:
                self._covers.apply(
                    actor=command.actor,
                    book_id=command.book_id,
                    resource_id=command.resource_id,
                    scope=command.scope,
                    cover_url=str(command.candidate.cover_url),
                    now=command.now,
                )
            except Exception:
                LOGGER.warning(
                    "metadata_apply provider=%s target_scope=%s resource_id=%s "
                    "stage=cover outcome=failed book_id=%s",
                    command.candidate.source,
                    command.scope.value,
                    command.resource_id,
                    command.book_id,
                    exc_info=True,
                )
                cover_status = "failed"
            else:
                cover_status = "applied"
                applied.append(cover_field)

        return ApplyRecognizedMetadataResult(
            applied_fields=tuple(applied),
            skipped_fields=tuple(skipped),
            cover_status=cover_status,
        )

    @staticmethod
    def _field_values(
        field: RecognizedMetadataField,
        state: RecognizedMetadataTargetState,
        candidate: RecognizedMetadataCandidate,
    ) -> tuple[object, object]:
        book = state.book
        resource = state.resource
        values: dict[RecognizedMetadataField, tuple[object, object]] = {
            RecognizedMetadataField.BOOK_TITLE: (book.title, _text(candidate.title)),
            RecognizedMetadataField.BOOK_AUTHOR: (book.author, _text(candidate.author)),
            RecognizedMetadataField.BOOK_DESCRIPTION: (
                book.description,
                _text(candidate.description),
            ),
            RecognizedMetadataField.BOOK_SERIES_NAME: (
                book.series_name,
                _text(candidate.series_name),
            ),
            RecognizedMetadataField.BOOK_SERIES_INDEX: (
                book.series_index,
                _number(candidate.series_index),
            ),
            RecognizedMetadataField.BOOK_TAGS: (book.tags, _tags(candidate.tags)),
        }
        if resource is not None:
            values.update(
                {
                    RecognizedMetadataField.RESOURCE_TITLE: (
                        resource.title,
                        _text(candidate.title),
                    ),
                    RecognizedMetadataField.RESOURCE_DESCRIPTION: (
                        resource.description,
                        _text(candidate.description),
                    ),
                    RecognizedMetadataField.RESOURCE_PUBLISHER: (
                        resource.publisher,
                        _text(candidate.publisher),
                    ),
                    RecognizedMetadataField.RESOURCE_PUBLISHED_AT: (
                        resource.published_at,
                        candidate.published_at,
                    ),
                    RecognizedMetadataField.RESOURCE_LANGUAGE: (
                        resource.language,
                        _text(candidate.language),
                    ),
                    RecognizedMetadataField.RESOURCE_ISBN: (
                        resource.isbn,
                        _text(candidate.isbn),
                    ),
                    RecognizedMetadataField.RESOURCE_IDENTIFIER: (
                        resource.identifier,
                        _text(candidate.identifier),
                    ),
                    RecognizedMetadataField.RESOURCE_NARRATOR: (
                        resource.narrator,
                        _text(candidate.narrator),
                    ),
                    RecognizedMetadataField.RESOURCE_ABRIDGED: (
                        resource.abridged,
                        candidate.abridged,
                    ),
                    RecognizedMetadataField.RESOURCE_INDEX: (
                        resource.resource_index,
                        _number(candidate.resource_index),
                    ),
                }
            )
        try:
            return values[field]
        except KeyError as exc:
            raise InvalidRecognizedMetadataError(
                "metadata field is unavailable"
            ) from exc

    @staticmethod
    def _assign(
        field: RecognizedMetadataField,
        value: object,
        book_changes: BookMetadataChanges,
        resource_changes: RecognizedResourceChanges,
    ) -> None:
        if field is RecognizedMetadataField.BOOK_TITLE:
            book_changes["title"] = str(value)
        elif field is RecognizedMetadataField.BOOK_AUTHOR:
            book_changes["author"] = str(value)
        elif field is RecognizedMetadataField.BOOK_DESCRIPTION:
            book_changes["description"] = str(value)
        elif field is RecognizedMetadataField.BOOK_SERIES_NAME:
            book_changes["series_name"] = str(value)
        elif field is RecognizedMetadataField.BOOK_SERIES_INDEX:
            book_changes["series_index"] = _required_number(value)
        elif field is RecognizedMetadataField.RESOURCE_TITLE:
            resource_changes["title"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_DESCRIPTION:
            resource_changes["description"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_PUBLISHER:
            resource_changes["publisher"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_PUBLISHED_AT and isinstance(
            value, datetime
        ):
            resource_changes["published_at"] = value
        elif field is RecognizedMetadataField.RESOURCE_LANGUAGE:
            resource_changes["language"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_ISBN:
            resource_changes["isbn"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_IDENTIFIER:
            resource_changes["identifier"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_NARRATOR:
            resource_changes["narrator"] = str(value)
        elif field is RecognizedMetadataField.RESOURCE_ABRIDGED and isinstance(
            value, bool
        ):
            resource_changes["abridged"] = value
        elif field is RecognizedMetadataField.RESOURCE_INDEX:
            resource_changes["resource_index"] = _required_number(value)


__all__ = [
    "ApplyRecognizedCover",
    "ApplyRecognizedMetadata",
    "ApplyRecognizedMetadataCommand",
    "ApplyRecognizedMetadataResult",
    "BookMetadataChanges",
    "BookMetadataState",
    "InvalidRecognizedMetadataError",
    "MetadataTargetScope",
    "PublishedRecognizedCover",
    "RecognizedCoverApplication",
    "RecognizedCoverMetadataPort",
    "RecognizedCoverPublicationPort",
    "RecognizedCoverState",
    "RecognizedMetadataAuthorizationError",
    "RecognizedMetadataCandidate",
    "RecognizedMetadataField",
    "RecognizedMetadataPort",
    "RecognizedMetadataTargetNotFoundError",
    "RecognizedMetadataTargetState",
    "RecognizedMetadataUnitOfWork",
    "RecognizedResourceChanges",
    "RemoteCoverDownloadPort",
    "ResourceMetadataState",
]
