"""Application use cases for Resource metadata and media classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NotRequired, Protocol, TypedDict, cast


@dataclass(frozen=True, slots=True)
class LibraryActor:
    user_id: str
    can_manage_system: bool
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceContext:
    id: str
    book_id: str
    media_kind: str
    sort_order: int


class ResourceMetadataChanges(TypedDict, total=False):
    title: NotRequired[str]
    description: NotRequired[str | None]
    publisher: NotRequired[str | None]
    published_at: NotRequired[datetime | None]
    language: NotRequired[str | None]
    identifier: NotRequired[str | None]
    isbn: NotRequired[str | None]
    narrator: NotRequired[str | None]
    abridged: NotRequired[bool | None]
    resource_index: NotRequired[float | None]


@dataclass(frozen=True, slots=True)
class OperationSummary:
    id: str
    action: str
    status: str
    summary: str
    expires_at: datetime
    undo_available: bool


@dataclass(frozen=True, slots=True)
class ResourceReclassifyOutcome:
    affected_resource_ids: tuple[str, ...]
    operation: OperationSummary


@dataclass(frozen=True, slots=True)
class SetResourceMediaKindsCommand:
    resource_ids: tuple[str, ...]
    target_media_kind: str


@dataclass(frozen=True, slots=True)
class SetResourceMediaKindsOutcome:
    affected_resource_ids: tuple[str, ...]
    operation_ids: tuple[str, ...]


class ResourceMetadataPort(Protocol):
    def can_access_book(self, *, actor: LibraryActor, book_id: str) -> bool: ...

    def get_resource_context(
        self, *, actor: LibraryActor, book_id: str, resource_id: str
    ) -> ResourceContext | None: ...

    def get_resource_contexts(
        self,
        *,
        actor: LibraryActor,
        book_id: str,
        resource_ids: tuple[str, ...],
    ) -> tuple[ResourceContext, ...]: ...

    def update_resource(
        self, *, resource_id: str, changes: ResourceMetadataChanges, now: datetime
    ) -> None: ...

    def reclassify_resource(
        self,
        *,
        actor_id: str,
        book_id: str,
        resource_id: str,
        target_media_kind: str,
        apply_to: Literal["RESOURCE", "SAME_MEDIA_KIND"],
        now: datetime,
    ) -> ResourceReclassifyOutcome: ...

    def set_media_kinds(
        self,
        *,
        actor_id: str,
        book_id: str,
        contexts: tuple[ResourceContext, ...],
        target_media_kind: str,
        now: datetime,
    ) -> SetResourceMediaKindsOutcome: ...


class UnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ResourceNotFoundError(Exception):
    """The requested Resource is not visible to the actor."""


class BookNotFoundError(Exception):
    """The requested Book is not visible to the actor."""


class LibraryAuthorizationError(Exception):
    """The actor cannot perform a management mutation."""


class InvalidResourceChangeError(Exception):
    """The requested Resource mutation is invalid."""


def set_resource_media_kinds(
    port: ResourceMetadataPort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    book_id: str,
    command: SetResourceMediaKindsCommand,
    now: datetime,
) -> SetResourceMediaKindsOutcome:
    _require_book_access(port, actor=actor, book_id=book_id)
    _require_manager(actor)
    if not command.resource_ids:
        raise InvalidResourceChangeError("RESOURCE_SELECTION_REQUIRED")
    if len(set(command.resource_ids)) != len(command.resource_ids):
        raise InvalidResourceChangeError("DUPLICATE_RESOURCE_IDS")
    contexts = list(
        port.get_resource_contexts(
            actor=actor,
            book_id=book_id,
            resource_ids=command.resource_ids,
        )
    )
    if {context.id for context in contexts} != set(command.resource_ids):
        raise ResourceNotFoundError
    contexts.sort(key=lambda value: (value.sort_order, value.id))
    target_media_kind = command.target_media_kind.strip().upper()
    _require_media_kind(target_media_kind)
    try:
        outcome = port.set_media_kinds(
            actor_id=actor.user_id,
            book_id=book_id,
            contexts=tuple(contexts),
            target_media_kind=target_media_kind,
            now=now,
        )
        unit_of_work.commit()
    except ValueError as exc:
        unit_of_work.rollback()
        raise ResourceNotFoundError(str(exc)) from exc
    except Exception:
        unit_of_work.rollback()
        raise
    return outcome


def reclassify_resource(
    port: ResourceMetadataPort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    book_id: str,
    resource_id: str,
    target_media_kind: str,
    apply_to: str,
    now: datetime,
) -> ResourceReclassifyOutcome:
    _require_book_access(port, actor=actor, book_id=book_id)
    _require_manager(actor)
    _require_resource(port, actor=actor, book_id=book_id, resource_id=resource_id)
    normalized_kind = target_media_kind.strip().upper()
    _require_media_kind(normalized_kind)
    if apply_to not in {"RESOURCE", "SAME_MEDIA_KIND"}:
        raise InvalidResourceChangeError("INVALID_RECLASSIFY_SCOPE")
    scope = cast(Literal["RESOURCE", "SAME_MEDIA_KIND"], apply_to)
    try:
        outcome = port.reclassify_resource(
            actor_id=actor.user_id,
            book_id=book_id,
            resource_id=resource_id,
            target_media_kind=normalized_kind,
            apply_to=scope,
            now=now,
        )
        unit_of_work.commit()
        return outcome
    except Exception:
        unit_of_work.rollback()
        raise


def update_resource(
    port: ResourceMetadataPort,
    unit_of_work: UnitOfWork,
    *,
    actor: LibraryActor,
    book_id: str,
    resource_id: str,
    changes: ResourceMetadataChanges,
    now: datetime,
) -> None:
    _require_book_access(port, actor=actor, book_id=book_id)
    _require_manager(actor)
    _require_resource(port, actor=actor, book_id=book_id, resource_id=resource_id)
    try:
        port.update_resource(resource_id=resource_id, changes=changes, now=now)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def _require_manager(actor: LibraryActor) -> None:
    if not actor.can_manage_system:
        raise LibraryAuthorizationError


def _require_book_access(
    port: ResourceMetadataPort, *, actor: LibraryActor, book_id: str
) -> None:
    if not port.can_access_book(actor=actor, book_id=book_id):
        raise BookNotFoundError


def _require_resource(
    port: ResourceMetadataPort,
    *,
    actor: LibraryActor,
    book_id: str,
    resource_id: str,
) -> ResourceContext:
    context = port.get_resource_context(
        actor=actor,
        book_id=book_id,
        resource_id=resource_id,
    )
    if context is None:
        raise ResourceNotFoundError
    return context


def _require_media_kind(value: str) -> None:
    if value not in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        raise InvalidResourceChangeError("INVALID_MEDIA_KIND")


__all__ = [
    "BookNotFoundError",
    "InvalidResourceChangeError",
    "LibraryActor",
    "LibraryAuthorizationError",
    "OperationSummary",
    "ResourceContext",
    "ResourceMetadataChanges",
    "ResourceMetadataPort",
    "ResourceNotFoundError",
    "ResourceReclassifyOutcome",
    "SetResourceMediaKindsCommand",
    "SetResourceMediaKindsOutcome",
    "reclassify_resource",
    "set_resource_media_kinds",
    "update_resource",
]
