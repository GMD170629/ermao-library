"""Kindle capability composition root."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.bootstrap.system import write_prepared_system_events
from app.core.authorization import (
    prepare_user_preference_write,
    write_prepared_user_preference,
)
from app.modules.kindle.infrastructure.tasks import (
    cancel_queued_kindle_task,
    create_kindle_send_task,
    delete_kindle_send_task,
    entity_as_legacy_dict,
    execute_kindle_send_task_insert,
    execute_kindle_send_task_update,
    find_active_kindle_task,
    get_kindle_send_task,
    get_library_file_details_for_kindle,
    has_table,
    list_kindle_send_tasks,
    mark_kindle_task_failed,
    mark_kindle_task_sent,
    mark_kindle_tasks_unknown,
    prepare_claim_kindle_send_task,
    prepare_kindle_send_snapshot_update,
    prepare_kindle_send_task_insert,
    retry_kindle_task,
    schedule_kindle_retry,
)
from app.modules.kindle.public import KindleWriteTransaction
from app.modules.system.domain.events import PreparedSystemEvent
from app.services.email_settings import (
    PreparedEmailSettingsUpdate,
    write_prepared_email_settings,
)


def record_kindle_event_command(
    db: Session, event: PreparedSystemEvent
) -> None:
    with KindleWriteTransaction(db):
        write_prepared_system_events(db, (event,))


def update_email_settings_command(
    db: Session,
    prepared: PreparedEmailSettingsUpdate,
    *,
    event: PreparedSystemEvent,
) -> None:
    with KindleWriteTransaction(db):
        write_prepared_email_settings(db, prepared)
        write_prepared_system_events(db, (event,))


def update_kindle_recipient_command(
    db: Session, *, user_id: str, email: str
) -> None:
    statement = prepare_user_preference_write(user_id, "kindle.email", email)
    with KindleWriteTransaction(db):
        write_prepared_user_preference(db, statement)


def create_kindle_send_task_command(
    db: Session,
    values: dict[str, Any],
    *,
    event: PreparedSystemEvent,
) -> None:
    statement = prepare_kindle_send_task_insert(values)
    with KindleWriteTransaction(db):
        execute_kindle_send_task_insert(db, statement)
        write_prepared_system_events(db, (event,))


def cancel_kindle_send_task_command(
    db: Session,
    task_id: str,
    *,
    timestamp: datetime,
    event: PreparedSystemEvent,
) -> int:
    with KindleWriteTransaction(db):
        changed = cancel_queued_kindle_task(db, task_id, timestamp)
        if changed == 1:
            write_prepared_system_events(db, (event,))
    return changed


def retry_kindle_send_task_command(
    db: Session,
    task_id: str,
    *,
    timestamp: datetime,
    event: PreparedSystemEvent,
) -> None:
    with KindleWriteTransaction(db):
        retry_kindle_task(db, task_id, timestamp)
        write_prepared_system_events(db, (event,))


def delete_kindle_send_task_command(
    db: Session, task_id: str, *, event: PreparedSystemEvent
) -> None:
    with KindleWriteTransaction(db):
        delete_kindle_send_task(db, task_id)
        write_prepared_system_events(db, (event,))


def claim_kindle_send_task_command(
    db: Session, task_id: str, *, timestamp: datetime
) -> dict[str, Any] | None:
    if not has_table(db, "KindleSendTask"):
        return None
    db.close()
    statement = prepare_claim_kindle_send_task(task_id, now=timestamp)
    with KindleWriteTransaction(db):
        task = execute_kindle_send_task_update(db, statement)
    return entity_as_legacy_dict(task) if task is not None else None


def update_kindle_send_snapshot_command(
    db: Session,
    task_id: str,
    *,
    sender_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_security: str,
    smtp_username: str | None,
    message_id: str,
    timestamp: datetime,
) -> dict[str, Any] | None:
    statement = prepare_kindle_send_snapshot_update(
        task_id,
        sender_email=sender_email,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_security=smtp_security,
        smtp_username=smtp_username,
        message_id=message_id,
        now=timestamp,
    )
    with KindleWriteTransaction(db):
        task = execute_kindle_send_task_update(db, statement)
    return entity_as_legacy_dict(task) if task is not None else None


def schedule_kindle_retry_command(
    db: Session,
    task_id: str,
    *,
    retry_at: datetime,
    error_message: str,
    timestamp: datetime,
    event: PreparedSystemEvent,
) -> None:
    with KindleWriteTransaction(db):
        schedule_kindle_retry(
            db,
            task_id,
            retry_at=retry_at,
            error_message=error_message,
            now=timestamp,
        )
        write_prepared_system_events(db, (event,))


def fail_kindle_send_task_command(
    db: Session,
    task_id: str,
    *,
    error_message: str,
    timestamp: datetime,
    event: PreparedSystemEvent,
) -> None:
    with KindleWriteTransaction(db):
        mark_kindle_task_failed(
            db, task_id, error_message=error_message, now=timestamp
        )
        write_prepared_system_events(db, (event,))


def complete_kindle_send_task_command(
    db: Session,
    task_id: str,
    *,
    sent_at: datetime,
    event: PreparedSystemEvent,
) -> None:
    with KindleWriteTransaction(db):
        mark_kindle_task_sent(db, task_id, sent_at)
        write_prepared_system_events(db, (event,))


def recover_interrupted_kindle_tasks_command(
    db: Session,
    *,
    task_ids: tuple[str, ...],
    error_message: str,
    timestamp: datetime,
    events: tuple[PreparedSystemEvent, ...],
) -> None:
    with KindleWriteTransaction(db):
        mark_kindle_tasks_unknown(
            db,
            task_ids,
            error_message=error_message,
            now=timestamp,
        )
        write_prepared_system_events(db, events)

__all__ = [
    "cancel_queued_kindle_task",
    "cancel_kindle_send_task_command",
    "claim_kindle_send_task_command",
    "complete_kindle_send_task_command",
    "create_kindle_send_task",
    "create_kindle_send_task_command",
    "delete_kindle_send_task",
    "delete_kindle_send_task_command",
    "fail_kindle_send_task_command",
    "find_active_kindle_task",
    "get_kindle_send_task",
    "get_library_file_details_for_kindle",
    "has_table",
    "list_kindle_send_tasks",
    "record_kindle_event_command",
    "recover_interrupted_kindle_tasks_command",
    "retry_kindle_task",
    "retry_kindle_send_task_command",
    "schedule_kindle_retry_command",
    "update_kindle_recipient_command",
    "update_email_settings_command",
    "update_kindle_send_snapshot_command",
]
