"""Structured logging, clock, unit-of-work, and best-effort sidecar hooks."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.imports.application.readable_resource.ports import (
    ClockPort,
    PipelineLogPort,
    SidecarWritebackPort,
    UnitOfWorkPort,
)

logger = logging.getLogger("ermao.readable_resource_pipeline")


class StructuredPipelineLog(PipelineLogPort):
    def emit(
        self,
        event: str,
        *,
        library_id: str | None = None,
        resource_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        outcome: str | None = None,
    ) -> None:
        logger.info(
            event,
            extra={
                "library_id": library_id,
                "resource_id": resource_id,
                "task_id": task_id,
                "stage": stage,
                "outcome": outcome,
            },
        )


class UtcClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class SqlAlchemyUnitOfWork(UnitOfWorkPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def release_before_io(self) -> None:
        session = self._session
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("release_before_io called with pending session changes")
        if session.in_transaction():
            session.rollback()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def rollback(self) -> None:
        self._session.rollback()

    def recover_after_failure(self) -> None:
        self._session.rollback()


class InMemorySidecarWriteback(SidecarWritebackPort):
    """Test-only sidecar scheduler that records resource ids in memory."""

    def __init__(self) -> None:
        self.scheduled: list[str] = []

    def schedule_after_commit(self, resource_id: str) -> None:
        self.scheduled.append(resource_id)


class BestEffortSidecarWriteback(SidecarWritebackPort):
    """Call an optional public writeback; failures are logged only."""

    def __init__(self, writeback_fn: Callable[[str], None] | None = None) -> None:
        self._writeback = writeback_fn

    def schedule_after_commit(self, resource_id: str) -> None:
        if self._writeback is None:
            logger.info(
                "readable_resource.sidecar.skipped",
                extra={
                    "resource_id": resource_id,
                    "stage": "sidecar",
                    "outcome": "noop",
                },
            )
            return
        try:
            self._writeback(resource_id)
            logger.info(
                "readable_resource.sidecar.ok",
                extra={
                    "resource_id": resource_id,
                    "stage": "sidecar",
                    "outcome": "ok",
                },
            )
        except Exception:
            logger.exception(
                "readable_resource.sidecar.failed",
                extra={
                    "resource_id": resource_id,
                    "stage": "sidecar",
                    "outcome": "error",
                },
            )


__all__ = [
    "BestEffortSidecarWriteback",
    "InMemorySidecarWriteback",
    "SqlAlchemyUnitOfWork",
    "StructuredPipelineLog",
    "UtcClock",
]
