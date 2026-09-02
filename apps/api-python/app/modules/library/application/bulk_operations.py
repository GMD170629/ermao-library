"""Application commands for auditable multi-Book operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.authorization import AuthorizationContext
from app.modules.library.application.resource_commands import OperationSummary

BulkFindReplaceField = Literal[
    "title",
    "author",
    "description",
    "seriesName",
    "tags",
    "resourceTitle",
]
BulkCoverAction = Literal["crop", "regenerate", "compress", "replace"]


@dataclass(frozen=True, slots=True)
class BulkMetadataCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]
    fields: Mapping[str, str]
    add_tags: tuple[str, ...]
    remove_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkFindReplaceCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]
    field: BulkFindReplaceField
    find: str
    replacement: str
    regex: bool
    case_sensitive: bool
    start_number: int


@dataclass(frozen=True, slots=True)
class BulkShelfMembershipCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]
    shelf_id: str
    membership: Literal["ADD", "REMOVE"]


@dataclass(frozen=True, slots=True)
class BulkReadingStatusCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]
    status: Literal["UNREAD", "FINISHED"]


@dataclass(frozen=True, slots=True)
class BulkCoverCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]
    action: BulkCoverAction
    ratio: str
    quality: int
    max_dimension: int
    cover_content: bytes | None


@dataclass(frozen=True, slots=True)
class FindReplacePreviewItem:
    book_id: str
    title: str
    before: str | tuple[str, ...]
    after: str | tuple[str, ...]
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class FindReplacePreview:
    changed_books: int
    changed_values: int
    items: tuple[FindReplacePreviewItem, ...]


@dataclass(frozen=True, slots=True)
class BulkBookOperationResult:
    updated: int
    changed_values: int
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class BulkCoverSkipped:
    book_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class BulkCoverResult:
    updated: int
    skipped: tuple[BulkCoverSkipped, ...]
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class PreparedBulkCoverResult:
    outcome: BulkCoverResult
    completion_token: object


class BulkBookOperationPort(Protocol):
    def accessible_book_ids(
        self,
        *,
        context: AuthorizationContext,
        book_ids: tuple[str, ...],
    ) -> tuple[str, ...]: ...

    def update_metadata(
        self, command: BulkMetadataCommand
    ) -> BulkBookOperationResult: ...

    def preview_find_replace(
        self, command: BulkFindReplaceCommand
    ) -> FindReplacePreview: ...

    def apply_find_replace(
        self, command: BulkFindReplaceCommand
    ) -> BulkBookOperationResult: ...

    def update_shelf_membership(
        self, command: BulkShelfMembershipCommand
    ) -> BulkBookOperationResult: ...

    def update_reading_status(
        self, command: BulkReadingStatusCommand
    ) -> BulkBookOperationResult: ...

    def prepare_covers(self, command: BulkCoverCommand) -> PreparedBulkCoverResult: ...

    def complete_covers(self, prepared: PreparedBulkCoverResult) -> None: ...

    def revert_covers(self, prepared: PreparedBulkCoverResult) -> None: ...


class BulkBookOperationUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class BulkCoverRegenerator(Protocol):
    def execute(self, command: BulkCoverCommand) -> BulkCoverResult: ...


class InvalidBulkBookOperationError(Exception):
    """The requested batch action is malformed or violates a domain policy."""


class BulkBookAccessError(Exception):
    """At least one selected Book is not visible to the current actor."""


class BulkBookAuthorizationError(Exception):
    """The actor lacks system-management permission for a metadata action."""


def _validate_selection(
    port: BulkBookOperationPort,
    *,
    context: AuthorizationContext,
    book_ids: tuple[str, ...],
) -> None:
    if not book_ids:
        raise InvalidBulkBookOperationError("BOOK_SELECTION_REQUIRED")
    if len(book_ids) > 500:
        raise InvalidBulkBookOperationError("BOOK_SELECTION_TOO_LARGE")
    if len(set(book_ids)) != len(book_ids):
        raise InvalidBulkBookOperationError("DUPLICATE_BOOK_IDS")
    if port.accessible_book_ids(context=context, book_ids=book_ids) != book_ids:
        raise BulkBookAccessError


def _execute(
    unit_of_work: BulkBookOperationUnitOfWork,
    callback,
):
    try:
        result = callback()
        unit_of_work.commit()
        return result
    except Exception:
        unit_of_work.rollback()
        raise


class ExecuteBulkMetadata:
    def __init__(
        self, port: BulkBookOperationPort, unit_of_work: BulkBookOperationUnitOfWork
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkMetadataCommand) -> BulkBookOperationResult:
        _validate_selection(
            self._port, context=command.context, book_ids=command.book_ids
        )
        if not command.context.can_manage_system:
            raise BulkBookAuthorizationError
        if set(command.fields) - {"author", "seriesName"}:
            raise InvalidBulkBookOperationError("UNSUPPORTED_METADATA_FIELD")
        if not command.fields and not command.add_tags and not command.remove_tags:
            raise InvalidBulkBookOperationError("EMPTY_METADATA_CHANGE")
        return _execute(
            self._unit_of_work,
            lambda: self._port.update_metadata(command),
        )


class PreviewBulkFindReplace:
    def __init__(self, port: BulkBookOperationPort) -> None:
        self._port = port

    def execute(self, command: BulkFindReplaceCommand) -> FindReplacePreview:
        _validate_selection(
            self._port, context=command.context, book_ids=command.book_ids
        )
        if not command.context.can_manage_system:
            raise BulkBookAuthorizationError
        if not command.find:
            raise InvalidBulkBookOperationError("FIND_TEXT_REQUIRED")
        return self._port.preview_find_replace(command)


class ExecuteBulkFindReplace:
    def __init__(
        self, port: BulkBookOperationPort, unit_of_work: BulkBookOperationUnitOfWork
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkFindReplaceCommand) -> BulkBookOperationResult:
        PreviewBulkFindReplace(self._port).execute(command)
        return _execute(
            self._unit_of_work,
            lambda: self._port.apply_find_replace(command),
        )


class ExecuteBulkShelfMembership:
    def __init__(
        self, port: BulkBookOperationPort, unit_of_work: BulkBookOperationUnitOfWork
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkShelfMembershipCommand) -> BulkBookOperationResult:
        _validate_selection(
            self._port, context=command.context, book_ids=command.book_ids
        )
        if not command.shelf_id:
            raise InvalidBulkBookOperationError("SHELF_REQUIRED")
        return _execute(
            self._unit_of_work,
            lambda: self._port.update_shelf_membership(command),
        )


class ExecuteBulkReadingStatus:
    def __init__(
        self, port: BulkBookOperationPort, unit_of_work: BulkBookOperationUnitOfWork
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def execute(self, command: BulkReadingStatusCommand) -> BulkBookOperationResult:
        _validate_selection(
            self._port, context=command.context, book_ids=command.book_ids
        )
        return _execute(
            self._unit_of_work,
            lambda: self._port.update_reading_status(command),
        )


class ExecuteBulkCovers:
    def __init__(
        self,
        port: BulkBookOperationPort,
        unit_of_work: BulkBookOperationUnitOfWork,
        regenerator: BulkCoverRegenerator,
    ) -> None:
        self._port = port
        self._unit_of_work = unit_of_work
        self._regenerator = regenerator

    def execute(self, command: BulkCoverCommand) -> BulkCoverResult:
        _validate_selection(
            self._port, context=command.context, book_ids=command.book_ids
        )
        if not command.context.can_manage_system:
            raise BulkBookAuthorizationError
        if command.action == "crop" and command.ratio not in {"2:3", "3:4", "1:1"}:
            raise InvalidBulkBookOperationError("INVALID_COVER_RATIO")
        if command.action == "replace" and command.cover_content is None:
            raise InvalidBulkBookOperationError("COVER_FILE_REQUIRED")
        if command.action != "replace" and command.cover_content is not None:
            raise InvalidBulkBookOperationError("UNEXPECTED_COVER_FILE")
        if command.action == "regenerate":
            return self._regenerator.execute(command)
        prepared: PreparedBulkCoverResult | None = None
        try:
            prepared = self._port.prepare_covers(command)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            if prepared is not None:
                self._port.revert_covers(prepared)
            raise
        self._port.complete_covers(prepared)
        return prepared.outcome


__all__ = [
    "BulkBookAccessError",
    "BulkBookAuthorizationError",
    "BulkBookOperationPort",
    "BulkBookOperationResult",
    "BulkCoverAction",
    "BulkCoverCommand",
    "BulkCoverRegenerator",
    "BulkCoverResult",
    "BulkCoverSkipped",
    "BulkFindReplaceCommand",
    "BulkFindReplaceField",
    "BulkMetadataCommand",
    "BulkReadingStatusCommand",
    "BulkShelfMembershipCommand",
    "ExecuteBulkCovers",
    "ExecuteBulkFindReplace",
    "ExecuteBulkMetadata",
    "ExecuteBulkReadingStatus",
    "ExecuteBulkShelfMembership",
    "FindReplacePreview",
    "FindReplacePreviewItem",
    "InvalidBulkBookOperationError",
    "PreparedBulkCoverResult",
    "PreviewBulkFindReplace",
]
