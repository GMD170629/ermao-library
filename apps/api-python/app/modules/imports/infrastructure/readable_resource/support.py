"""Structured logging, clock, and unit-of-work for the target pipeline."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

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
        run_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        outcome: str | None = None,
    ) -> None:
        logger.info(
            event,
            extra={
                "library_id": library_id,
                "resource_id": resource_id,
                "run_id": run_id,
                "task_id": task_id,
                "stage": stage,
                "outcome": outcome,
            },
        )


class UtcClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)


class SqlAlchemyUnitOfWork(UnitOfWorkPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def release_before_io(self) -> None:
        session = self._session
        if session.new or session.dirty or session.deleted:
            raise RuntimeError(
                "release_before_io called with pending session changes"
            )
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


class DeferredSidecarWriteback(SidecarWritebackPort):
    """Schedules recoverable sidecar writeback after commit; no-op until phase 7."""

    def __init__(self) -> None:
        self._pending: list[str] = []

    def schedule_after_commit(self, resource_id: str) -> None:
        self._pending.append(resource_id)
        logger.info(
            "readable_resource.sidecar.scheduled",
            extra={"resource_id": resource_id, "stage": "sidecar", "outcome": "queued"},
        )
