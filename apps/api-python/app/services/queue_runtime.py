from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from time import monotonic, time_ns
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.time import now_timestamp_ms, to_timestamp_ms


LOGGER = logging.getLogger(__name__)
ACTIVE_OPERATION_STATUSES = ("requested", "waiting", "running")
TERMINAL_OPERATION_STATUSES = ("completed", "failed")
HEARTBEAT_BUSY_TIMEOUT_MS = 1_000
DEFAULT_BUSY_TIMEOUT_MS = 10_000


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.get_bind()).get_table_names()
    except Exception:
        return False


def safe_runtime_error(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    value = (str(error).strip() or error.__class__.__name__) if isinstance(error, BaseException) else str(error).strip()
    if "database is locked" in value.lower():
        return "database-is-busy"
    value = re.sub(r"/(?:Users|home|var|Volumes|volume\d+|mnt|srv|opt)/[^\s'\"]+", "[local-path]", value)
    value = re.sub(r"[A-Z]:\\[^\s'\"]+", "[local-path]", value, flags=re.I)
    value = re.sub(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+", r"\1=[redacted]", value)
    return value[:1000]


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
    if not _has_table(db, "QueueRuntimeState"):
        return
    now = now_timestamp_ms()
    db.execute(
        text(
            """
            INSERT INTO `QueueRuntimeState`
                (`queueName`, `instanceId`, `status`, `pollIntervalSeconds`, `startedAt`,
                 `heartbeatAt`, `lastProcessedAt`, `lastError`, `updatedAt`)
            VALUES
                (:queue, :instance, :status, :poll, :now, :now, :processed, :error, :now)
            ON CONFLICT (`queueName`) DO UPDATE SET
                `instanceId` = excluded.`instanceId`,
                `status` = excluded.`status`,
                `pollIntervalSeconds` = excluded.`pollIntervalSeconds`,
                `startedAt` = CASE
                    WHEN `QueueRuntimeState`.`instanceId` != excluded.`instanceId`
                    THEN excluded.`startedAt` ELSE `QueueRuntimeState`.`startedAt` END,
                `heartbeatAt` = excluded.`heartbeatAt`,
                `lastProcessedAt` = COALESCE(excluded.`lastProcessedAt`, `QueueRuntimeState`.`lastProcessedAt`),
                `lastError` = CASE
                    WHEN excluded.`lastError` IS NOT NULL THEN excluded.`lastError`
                    WHEN excluded.`lastProcessedAt` IS NOT NULL THEN NULL
                    ELSE `QueueRuntimeState`.`lastError` END,
                `updatedAt` = excluded.`updatedAt`
            """
        ),
        {
            "queue": queue_name,
            "instance": instance_id,
            "status": status,
            "poll": float(poll_interval_seconds),
            "now": now,
            "processed": now if processed else None,
            "error": safe_runtime_error(error),
        },
    )
    db.commit()


class QueueHeartbeatPump:
    """Keep a consumer heartbeat fresh while it is idle or processing a long item."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
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
                    db.execute(text(f"PRAGMA busy_timeout = {HEARTBEAT_BUSY_TIMEOUT_MS}"))
                    try:
                        record_queue_heartbeat(
                            db,
                            queue_name=self._queue_name,
                            instance_id=self._instance_id,
                            poll_interval_seconds=self._poll_interval_seconds,
                            processed=processed,
                            error=error,
                        )
                    finally:
                        db.rollback()
                        db.execute(text(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}"))
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
                    db.execute(text(f"PRAGMA busy_timeout = {HEARTBEAT_BUSY_TIMEOUT_MS}"))
                    try:
                        mark_queue_stopped(
                            db,
                            queue_name=self._queue_name,
                            instance_id=self._instance_id,
                        )
                    finally:
                        db.rollback()
                        db.execute(text(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}"))
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
    if not _has_table(db, "QueueRuntimeState"):
        return
    now = now_timestamp_ms()
    db.execute(
        text(
            "UPDATE `QueueRuntimeState` SET `status` = 'stopped', `heartbeatAt` = :now, "
            "`updatedAt` = :now WHERE `queueName` = :queue AND `instanceId` = :instance"
        ),
        {"now": now, "queue": queue_name, "instance": instance_id},
    )
    db.commit()


def queue_runtime_view(db: Session, queue_name: str) -> dict[str, Any] | None:
    if not _has_table(db, "QueueRuntimeState"):
        return None
    row = db.execute(
        text("SELECT * FROM `QueueRuntimeState` WHERE `queueName` = :queue"),
        {"queue": queue_name},
    ).mappings().first()
    if not row:
        return None
    result = dict(row)
    heartbeat_ms = to_timestamp_ms(result.get("heartbeatAt"))
    poll = float(result.get("pollIntervalSeconds") or 0)
    stale_after_ms = int(max(30.0, poll * 3.0) * 1000)
    result["heartbeatAgeMs"] = max(0, now_timestamp_ms() - heartbeat_ms) if heartbeat_ms is not None else None
    result["staleAfterMs"] = stale_after_ms
    result["stale"] = heartbeat_ms is None or now_timestamp_ms() - heartbeat_ms > stale_after_ms
    return result


def create_restart_operation(db: Session, actor_user_id: str) -> tuple[dict[str, Any], bool]:
    if not _has_table(db, "QueueControlOperation"):
        raise RuntimeError("queue-control-unavailable")
    existing = db.execute(
        text(
            "SELECT * FROM `QueueControlOperation` WHERE `queueName` = 'import' "
            "AND `status` IN ('requested', 'waiting', 'running') "
            "ORDER BY CAST(`requestedAt` AS INTEGER) DESC LIMIT 1"
        )
    ).mappings().first()
    if existing:
        return dict(existing), False
    now = now_timestamp_ms()
    operation = {
        "id": f"queue_{uuid4().hex}",
        "queueName": "import",
        "action": "restart",
        "status": "requested",
        "actorUserId": actor_user_id,
        "messageCode": "queue.restart.requested",
        "requestedAt": now,
        "startedAt": None,
        "finishedAt": None,
        "updatedAt": now,
    }
    columns = ", ".join(f"`{key}`" for key in operation)
    values = ", ".join(f":{key}" for key in operation)
    db.execute(text(f"INSERT INTO `QueueControlOperation` ({columns}) VALUES ({values})"), operation)
    db.commit()
    return operation, True


def active_restart_operation(db: Session) -> dict[str, Any] | None:
    if not _has_table(db, "QueueControlOperation"):
        return None
    row = db.execute(
        text(
            "SELECT * FROM `QueueControlOperation` WHERE `queueName` = 'import' "
            "AND `status` IN ('requested', 'waiting', 'running') "
            "ORDER BY CAST(`requestedAt` AS INTEGER) ASC LIMIT 1"
        )
    ).mappings().first()
    return dict(row) if row else None


def update_restart_operation(db: Session, operation_id: str, status: str, message_code: str) -> None:
    if status not in (*ACTIVE_OPERATION_STATUSES, *TERMINAL_OPERATION_STATUSES):
        raise ValueError(status)
    now = now_timestamp_ms()
    started = ", `startedAt` = COALESCE(`startedAt`, :now)" if status in {"waiting", "running", "completed"} else ""
    finished = ", `finishedAt` = :now" if status in TERMINAL_OPERATION_STATUSES else ""
    db.execute(
        text(
            f"UPDATE `QueueControlOperation` SET `status` = :status, `messageCode` = :message, "
            f"`updatedAt` = :now{started}{finished} WHERE `id` = :id"
        ),
        {"id": operation_id, "status": status, "message": message_code, "now": now},
    )
    db.commit()


def queue_operation_view(db: Session, operation_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "QueueControlOperation"):
        return None
    row = db.execute(
        text("SELECT * FROM `QueueControlOperation` WHERE `id` = :id"),
        {"id": operation_id},
    ).mappings().first()
    return dict(row) if row else None
