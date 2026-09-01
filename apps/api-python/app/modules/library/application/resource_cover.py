"""Application use case for uploading a Resource cover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.modules.library.application.resource_commands import (
    BookNotFoundError,
    LibraryActor,
    LibraryAuthorizationError,
    ResourceMetadataPort,
    ResourceNotFoundError,
)

MAX_RESOURCE_COVER_BYTES = 10 * 1024 * 1024


class ResourceCoverPort(Protocol):
    """Persistence operations for a Resource cover replacement."""

    def current_cover_path(self, *, resource_id: str) -> str | None: ...

    def mark_ready(
        self, *, resource_id: str, cover_path: str, now: datetime
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedResourceCover:
    temporary_path: Path
    final_path: Path
    stored_path: str


@dataclass(frozen=True, slots=True)
class PublishedResourceCover:
    prepared: PreparedResourceCover
    backup_path: Path | None


class ResourceCoverPublicationPort(Protocol):
    def prepare(self, *, resource_id: str, content: bytes) -> PreparedResourceCover: ...

    def publish(
        self,
        prepared: PreparedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedResourceCover: ...

    def revert(self, published: PublishedResourceCover) -> None: ...

    def complete(
        self,
        published: PublishedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> None: ...


class ResourceCoverUnitOfWork(Protocol):
    """Transaction boundary for the Resource cover state change."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UploadResourceCoverCommand:
    actor: LibraryActor
    book_id: str
    resource_id: str
    content: bytes
    now: datetime


class UploadResourceCover:
    """Validate and atomically replace one readable Resource cover."""

    def __init__(
        self,
        access: ResourceMetadataPort,
        covers: ResourceCoverPort,
        publication: ResourceCoverPublicationPort,
        unit_of_work: ResourceCoverUnitOfWork,
    ) -> None:
        self._access = access
        self._covers = covers
        self._publication = publication
        self._unit_of_work = unit_of_work

    def execute(self, command: UploadResourceCoverCommand) -> str:
        if not command.actor.can_manage_system:
            raise LibraryAuthorizationError
        if not self._access.can_access_book(
            actor=command.actor, book_id=command.book_id
        ):
            raise BookNotFoundError
        context = self._access.get_resource_context(
            actor=command.actor,
            book_id=command.book_id,
            resource_id=command.resource_id,
        )
        if context is None:
            raise ResourceNotFoundError

        previous_cover_path = self._covers.current_cover_path(resource_id=context.id)
        prepared = self._publication.prepare(
            resource_id=context.id,
            content=command.content,
        )
        published = self._publication.publish(
            prepared,
            previous_stored_path=previous_cover_path,
        )
        try:
            self._covers.mark_ready(
                resource_id=context.id,
                cover_path=prepared.stored_path,
                now=command.now,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            self._publication.revert(published)
            raise
        self._publication.complete(
            published,
            previous_stored_path=previous_cover_path,
        )
        return context.id


__all__ = [
    "MAX_RESOURCE_COVER_BYTES",
    "PreparedResourceCover",
    "PublishedResourceCover",
    "ResourceCoverPort",
    "ResourceCoverPublicationPort",
    "ResourceCoverUnitOfWork",
    "UploadResourceCover",
    "UploadResourceCoverCommand",
]
