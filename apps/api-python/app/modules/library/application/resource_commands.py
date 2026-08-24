"""Application use cases for Resource metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NotRequired, Protocol, TypedDict


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
    expires_at: datetime | None
    undo_available: bool


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
    "update_resource",
]
