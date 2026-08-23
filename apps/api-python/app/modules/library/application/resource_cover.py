"""Application use case for regenerating a Resource cover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.library.application.resource_commands import ResourceNotFoundError


@dataclass(frozen=True, slots=True)
class ResourceCoverContext:
    resource_id: str
    book_id: str
    source_node_id: str


class ResourceCoverPort(Protocol):
    """Persistence operations for Resource cover regeneration."""

    def get_context(
        self, *, book_id: str, resource_id: str
    ) -> ResourceCoverContext | None: ...

    def mark_pending(self, *, resource_id: str, now: datetime) -> None: ...


class ResourceSourceContinuationPort(Protocol):
    """Queue boundary used after the cover state has been committed."""

    def enqueue_source_import(self, source_node_id: str) -> str | None: ...


class ResourceCoverUnitOfWork(Protocol):
    """Transaction boundary for the Resource cover state change."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RegenerateResourceCoverCommand:
    book_id: str
    resource_id: str
    now: datetime


@dataclass(frozen=True, slots=True)
class RegenerateResourceCoverResult:
    resource_id: str
    task_id: str | None


class RegenerateResourceCover:
    """Mark a Resource cover for regeneration, then enqueue its source."""

    def __init__(
        self,
        port: ResourceCoverPort,
        continuation: ResourceSourceContinuationPort,
        unit_of_work: ResourceCoverUnitOfWork,
    ) -> None:
        self._port = port
        self._continuation = continuation
        self._unit_of_work = unit_of_work

    def execute(
        self, command: RegenerateResourceCoverCommand
    ) -> RegenerateResourceCoverResult:
        context = self._port.get_context(
            book_id=command.book_id,
            resource_id=command.resource_id,
        )
        if context is None:
            raise ResourceNotFoundError
        try:
            self._port.mark_pending(
                resource_id=context.resource_id,
                now=command.now,
            )
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        task_id = self._continuation.enqueue_source_import(context.source_node_id)
        return RegenerateResourceCoverResult(
            resource_id=context.resource_id,
            task_id=task_id,
        )


__all__ = [
    "RegenerateResourceCover",
    "RegenerateResourceCoverCommand",
    "RegenerateResourceCoverResult",
    "ResourceCoverContext",
    "ResourceCoverPort",
    "ResourceCoverUnitOfWork",
    "ResourceSourceContinuationPort",
]
