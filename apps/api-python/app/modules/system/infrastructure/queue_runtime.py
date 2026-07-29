"""ORM persistence for queue heartbeat and control operations."""

from __future__ import annotations

import logging
import threading
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.time import now_timestamp_ms, to_timestamp_ms
from app.models.settings import QueueControlOperation, QueueRuntimeState
from app.modules.system.domain.queue import (
    ACTIVE_OPERATION_STATUSES,
    TERMINAL_OPERATION_STATUSES,
    enrich_queue_runtime_view,
    safe_runtime_error,
)
from app.modules.system.application.commands import execute_system_transaction

LOGGER = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]


def _runtime_row_dict(row: QueueRuntimeState) -> dict[str, Any]:
    return {
        "queueName": row.queue_name,
        "instanceId": row.instance_id,
        "status": row.status,
        "pollIntervalSeconds": row.poll_interval_seconds,
        "startedAt": row.started_at,
        "heartbeatAt": row.heartbeat_at,
        "lastProcessedAt": row.last_processed_at,
        "lastError": row.last_error,
        "updatedAt": row.updated_at,
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


def record_queue_heartbeat(
    db: Session,
    queue_name: str,
    instance_id: str,
    poll_interval_seconds: float,
    *,
    status: str = "running",
    processed: bool = False,
    error: BaseException | str | None = None,
) -> None:
    now = now_timestamp_ms()
    processed_at = now if processed else None
    error_text = safe_runtime_error(error)
    row = db.get(QueueRuntimeState, queue_name)
    if row is None:
        db.add(
            QueueRuntimeState(
                queue_name=queue_name,
                instance_id=instance_id,
                status=status,
                poll_interval_seconds=float(poll_interval_seconds),
                started_at=now,
                heartbeat_at=now,
                last_processed_at=processed_at,
                last_error=error_text,
                updated_at=now,
            )
        )
    else:
        if row.instance_id != instance_id:
            row.started_at = now  # type: ignore[assignment]
        row.instance_id = instance_id
        row.status = status
        row.poll_interval_seconds = float(poll_interval_seconds)
        row.heartbeat_at = now  # type: ignore[assignment]
        if processed_at is not None:
            row.last_processed_at = processed_at  # type: ignore[assignment]
        if error_text is not None:
            row.last_error = error_text
        elif processed_at is not None:
            row.last_error = None
        row.updated_at = now  # type: ignore[assignment]
    db.flush()


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
        with self._write_lock:
            try:
                with self._session_factory() as db:
                    execute_system_transaction(
                        db,
                        lambda: record_queue_heartbeat(
                            db,
                            queue_name=self._queue_name,
                            instance_id=self._instance_id,
                            poll_interval_seconds=self._poll_interval_seconds,
                            processed=processed,
                            error=error,
                        ),
                    )
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
        with self._write_lock:
            try:
                with self._session_factory() as db:
                    execute_system_transaction(
                        db,
                        lambda: mark_queue_stopped(
                            db,
                            queue_name=self._queue_name,
                            instance_id=self._instance_id,
                        ),
                    )
            except Exception as exc:
                LOGGER.warning(
                    "queue stopped state write deferred queue=%s error=%s",
                    self._queue_name,
                    safe_runtime_error(exc),
                )

    def _run(self) -> None:
        while not self._stop_event.wait(self._heartbeat_interval):
            self.pulse()

def mark_queue_stopped(db: Session, queue_name: str, instance_id: str) -> None:
    now = now_timestamp_ms()
    db.execute(
        update(QueueRuntimeState)
        .where(
            QueueRuntimeState.queue_name == queue_name,
            QueueRuntimeState.instance_id == instance_id,
        )
        .values(status="stopped", heartbeat_at=now, updated_at=now)
    )
    db.flush()


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


def create_queue_operation(
    db: Session,
    actor_user_id: str,
    *,
    action: str,
) -> tuple[dict[str, Any], bool]:
    if action not in {"restart", "clear"}:
        raise ValueError(action)
    existing = db.scalars(
        select(QueueControlOperation)
        .where(
            QueueControlOperation.queue_name == "import",
            QueueControlOperation.status.in_(ACTIVE_OPERATION_STATUSES),
        )
        .order_by(QueueControlOperation.requested_at.desc())
        .limit(1)
    ).first()
    if existing is not None:
        return _operation_row_dict(existing), False
    now = now_timestamp_ms()
    operation = QueueControlOperation(
        id=f"queue_{uuid4().hex}",
        queue_name="import",
        action=action,
        status="requested",
        actor_user_id=actor_user_id,
        message_code=f"queue.{action}.requested",
        requested_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )
    db.add(operation)
    db.flush()
    return _operation_row_dict(operation), True


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


def update_queue_operation(
    db: Session,
    operation_id: str,
    status: str,
    message_code: str,
) -> None:
    if status not in (*ACTIVE_OPERATION_STATUSES, *TERMINAL_OPERATION_STATUSES):
        raise ValueError(status)
    now = now_timestamp_ms()
    values: dict[str, Any] = {
        "status": status,
        "message_code": message_code,
        "updated_at": now,
    }
    row = db.get(QueueControlOperation, operation_id)
    if row is None:
        return
    if status in {"waiting", "running", "completed"} and row.started_at is None:
        values["started_at"] = now
    if status in TERMINAL_OPERATION_STATUSES:
        values["finished_at"] = now
    db.execute(update(QueueControlOperation).where(QueueControlOperation.id == operation_id).values(**values))
    db.flush()


def queue_operation_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    row = db.get(QueueControlOperation, operation_id)
    return _operation_row_dict(row) if row else None


def create_restart_operation(
    db: Session,
    actor_user_id: str,
) -> tuple[dict[str, Any], bool]:
    return create_queue_operation(db, actor_user_id, action="restart")


def active_restart_operation(db: Session) -> dict[str, Any] | None:
    return active_queue_operation(db)


def update_restart_operation(
    db: Session,
    operation_id: str,
    status: str,
    message_code: str,
) -> None:
    update_queue_operation(db, operation_id, status, message_code)
