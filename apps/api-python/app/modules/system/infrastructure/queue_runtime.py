"""ORM persistence for queue heartbeat and control operations."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.time import now_timestamp_ms, to_timestamp_ms
from app.models.settings import QueueControlOperation, QueueRuntimeState
from app.modules.system.application.commands import SystemWriteTransaction
from app.modules.system.domain.queue import (
    ACTIVE_OPERATION_STATUSES,
    TERMINAL_OPERATION_STATUSES,
    PreparedQueueHeartbeat,
    enrich_queue_runtime_view,
    prepare_queue_heartbeat,
    safe_runtime_error,
)

LOGGER = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class PreparedQueueRuntimeWrite:
    statement: Executable


@dataclass(frozen=True, slots=True)
class PreparedQueueOperationCreation:
    view: dict[str, Any]
    statement: Executable | None

    @property
    def created(self) -> bool:
        return self.statement is not None


def _runtime_row_dict(row: QueueRuntimeState) -> dict[str, Any]:
    return {
        "queueName": row.queue_name,
        "instanceId": row.instance_id,
        "status": row.status,
        "pollIntervalSeconds": row.poll_interval_seconds,
        "startedAt": to_timestamp_ms(row.started_at),
        "heartbeatAt": to_timestamp_ms(row.heartbeat_at),
        "lastProcessedAt": to_timestamp_ms(row.last_processed_at),
        "lastError": row.last_error,
        "updatedAt": to_timestamp_ms(row.updated_at),
    }


def _operation_row_dict(row: QueueControlOperation) -> dict[str, Any]:
    return {
        "id": row.id,
        "queueName": row.queue_name,
        "action": row.action,
        "status": row.status,
        "actorUserId": row.actor_user_id,
        "messageCode": row.message_code,
        "requestedAt": row.requested_at,
        "startedAt": row.started_at,
        "finishedAt": row.finished_at,
        "updatedAt": row.updated_at,
    }


def prepare_queue_heartbeat_write(
    prepared: PreparedQueueHeartbeat,
) -> PreparedQueueRuntimeWrite:
    statement = sqlite_insert(QueueRuntimeState).values(
        queue_name=prepared.queue_name,
        instance_id=prepared.instance_id,
        status=prepared.status,
        poll_interval_seconds=prepared.poll_interval_seconds,
        started_at=prepared.recorded_at,
        heartbeat_at=prepared.recorded_at,
        last_processed_at=prepared.processed_at,
        last_error=prepared.error_text,
        updated_at=prepared.recorded_at,
    )
    return PreparedQueueRuntimeWrite(
        statement=statement.on_conflict_do_update(
            index_elements=[QueueRuntimeState.queue_name],
            set_={
                QueueRuntimeState.instance_id: statement.excluded["instanceId"],
                QueueRuntimeState.status: statement.excluded.status,
                QueueRuntimeState.poll_interval_seconds: (
                    statement.excluded["pollIntervalSeconds"]
                ),
                QueueRuntimeState.started_at: case(
                    (
                        QueueRuntimeState.instance_id
                        != statement.excluded["instanceId"],
                        statement.excluded["startedAt"],
                    ),
                    else_=QueueRuntimeState.started_at,
                ),
                QueueRuntimeState.heartbeat_at: statement.excluded["heartbeatAt"],
                QueueRuntimeState.last_processed_at: (
                    statement.excluded["lastProcessedAt"]
                    if prepared.processed_at is not None
                    else QueueRuntimeState.last_processed_at
                ),
                QueueRuntimeState.last_error: (
                    statement.excluded["lastError"]
                    if prepared.error_text is not None
                    or prepared.processed_at is not None
                    else QueueRuntimeState.last_error
                ),
                QueueRuntimeState.updated_at: statement.excluded["updatedAt"],
            },
        ),
    )


def write_prepared_queue_runtime(
    db: Session,
    prepared: PreparedQueueRuntimeWrite,
) -> None:
    db.execute(prepared.statement)


class QueueHeartbeatPump:
    """Keep a consumer heartbeat fresh while it is idle or processing a long item."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        queue_name: str,
        instance_id: str,
        poll_interval_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._queue_name = queue_name
        self._instance_id = instance_id
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval = min(10.0, max(1.0, poll_interval_seconds))
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_write_warning_at = 0.0

    def start(self) -> None:
        self.pulse()
        self._thread = threading.Thread(
            target=self._run,
            name=f"{self._queue_name}-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def pulse(
        self,
        *,
        processed: bool = False,
        error: BaseException | str | None = None,
    ) -> None:
        prepared = prepare_queue_heartbeat(
            queue_name=self._queue_name,
            instance_id=self._instance_id,
            poll_interval_seconds=self._poll_interval_seconds,
            recorded_at=now_timestamp_ms(),
            processed=processed,
            error=error,
        )
        prepared_write = prepare_queue_heartbeat_write(prepared)
        with self._write_lock:
            try:
                with self._session_factory() as db:
                    with SystemWriteTransaction(db):
                        write_prepared_queue_runtime(db, prepared_write)
            except Exception as exc:
                now = monotonic()
                if now - self._last_write_warning_at >= 30:
                    LOGGER.warning(
                        "queue heartbeat write deferred queue=%s error=%s",
                        self._queue_name,
                        safe_runtime_error(exc),
                    )
                    self._last_write_warning_at = now

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._heartbeat_interval + 1)
        prepared_stop = prepare_queue_stopped_write(
            self._queue_name,
            self._instance_id,
            now=now_timestamp_ms(),
        )
        with self._write_lock:
            try:
                with self._session_factory() as db:
                    with SystemWriteTransaction(db):
                        write_prepared_queue_runtime(db, prepared_stop)
            except Exception as exc:
                LOGGER.warning(
                    "queue stopped state write deferred queue=%s error=%s",
                    self._queue_name,
                    safe_runtime_error(exc),
                )

    def _run(self) -> None:
        while not self._stop_event.wait(self._heartbeat_interval):
            self.pulse()


def prepare_queue_stopped_write(
    queue_name: str,
    instance_id: str,
    *,
    now: int,
) -> PreparedQueueRuntimeWrite:
    return PreparedQueueRuntimeWrite(
        update(QueueRuntimeState)
        .where(
            QueueRuntimeState.queue_name == queue_name,
            QueueRuntimeState.instance_id == instance_id,
        )
        .values(status="stopped", heartbeat_at=now, updated_at=now)
    )


def queue_runtime_view(db: Session, queue_name: str) -> dict[str, Any] | None:
    row = db.get(QueueRuntimeState, queue_name)
    if row is None:
        return None
    result = _runtime_row_dict(row)
    return enrich_queue_runtime_view(
        result,
        now_ms=now_timestamp_ms(),
        heartbeat_ms=to_timestamp_ms(result.get("heartbeatAt")),
    )


def prepare_queue_operation_creation(
    existing: dict[str, Any] | None,
    actor_user_id: str,
    *,
    action: str,
    operation_id: str,
    now: int,
) -> PreparedQueueOperationCreation:
    if action not in {"restart", "clear"}:
        raise ValueError(action)
    if existing is not None:
        return PreparedQueueOperationCreation(view=existing, statement=None)
    values = {
        "id": operation_id,
        "queue_name": "import",
        "action": action,
        "status": "requested",
        "actor_user_id": actor_user_id,
        "message_code": f"queue.{action}.requested",
        "requested_at": now,
        "started_at": None,
        "finished_at": None,
        "updated_at": now,
    }
    return PreparedQueueOperationCreation(
        view={
            "id": operation_id,
            "queueName": "import",
            "action": action,
            "status": "requested",
            "actorUserId": actor_user_id,
            "messageCode": f"queue.{action}.requested",
            "requestedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "updatedAt": now,
        },
        statement=sqlite_insert(QueueControlOperation).values(values),
    )


def write_prepared_queue_operation_creation(
    db: Session,
    prepared: PreparedQueueOperationCreation,
) -> tuple[dict[str, Any], bool]:
    if prepared.statement is not None:
        db.execute(prepared.statement)
    return prepared.view, prepared.created


def active_queue_operation(db: Session) -> dict[str, Any] | None:
    row = db.scalars(
        select(QueueControlOperation)
        .where(
            QueueControlOperation.queue_name == "import",
            QueueControlOperation.status.in_(ACTIVE_OPERATION_STATUSES),
        )
        .order_by(QueueControlOperation.requested_at.asc())
        .limit(1)
    ).first()
    return _operation_row_dict(row) if row else None


def prepare_queue_operation_update(
    operation_id: str,
    status: str,
    message_code: str,
    *,
    now: int,
) -> PreparedQueueRuntimeWrite:
    if status not in (*ACTIVE_OPERATION_STATUSES, *TERMINAL_OPERATION_STATUSES):
        raise ValueError(status)
    values: dict[str, Any] = {
        "status": status,
        "message_code": message_code,
        "updated_at": now,
    }
    values["started_at"] = case(
        (
            QueueControlOperation.started_at.is_(None)
            & (status in {"waiting", "running", "completed"}),
            now,
        ),
        else_=QueueControlOperation.started_at,
    )
    values["finished_at"] = (
        now
        if status in TERMINAL_OPERATION_STATUSES
        else QueueControlOperation.finished_at
    )
    return PreparedQueueRuntimeWrite(
        update(QueueControlOperation)
        .where(QueueControlOperation.id == operation_id)
        .values(**values)
    )


def queue_operation_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    row = db.get(QueueControlOperation, operation_id)
    return _operation_row_dict(row) if row else None


def active_restart_operation(db: Session) -> dict[str, Any] | None:
    return active_queue_operation(db)
