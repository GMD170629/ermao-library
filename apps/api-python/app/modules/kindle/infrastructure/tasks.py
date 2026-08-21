"""ORM persistence for Kindle send queue and HTTP routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert, Update

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import timestamp_ms_to_datetime
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.import_pipeline import KindleSendTask


def entity_record(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def _column_to_attribute(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def get_kindle_send_task(db: Session, task_id: str) -> dict[str, Any] | None:
    task = db.get(KindleSendTask, task_id)
    return entity_record(task) if task is not None else None


def list_kindle_send_tasks(
    db: Session,
    *,
    user_id: str,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = [KindleSendTask.user_id == user_id]
    if status:
        filters.append(KindleSendTask.status == status)
    total = int(
        db.scalar(select(func.count()).select_from(KindleSendTask).where(*filters)) or 0
    )
    rows = (
        db.execute(
            select(KindleSendTask)
            .where(*filters)
            .order_by(KindleSendTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return [entity_record(row) for row in rows], total


def find_active_kindle_task(
    db: Session,
    *,
    asset_id: str,
    recipient_email: str,
    exclude_task_id: str | None = None,
) -> dict[str, Any] | None:
    filters = [
        KindleSendTask.asset_id == asset_id,
        KindleSendTask.recipient_email == recipient_email,
        KindleSendTask.status.in_(("queued", "sending")),
    ]
    if exclude_task_id:
        filters.append(KindleSendTask.id != exclude_task_id)
    task = db.execute(
        select(KindleSendTask)
        .where(*filters)
        .order_by(KindleSendTask.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_record(task) if task is not None else None


def prepare_kindle_send_task_insert(values: dict[str, Any]) -> Insert:
    name_to_attr = _column_to_attribute(KindleSendTask)
    payload = {
        name_to_attr[key]: value for key, value in values.items() if key in name_to_attr
    }
    return insert(KindleSendTask).values(**payload).returning(KindleSendTask)


def create_kindle_send_task(db: Session, values: dict[str, Any]) -> KindleSendTask:
    return db.execute(prepare_kindle_send_task_insert(values)).scalar_one()


def execute_kindle_send_task_insert(
    db: Session,
    statement: Insert,
) -> KindleSendTask:
    return db.execute(statement).scalar_one()


def cancel_queued_kindle_task(db: Session, task_id: str, now: datetime) -> int:
    result = db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id, KindleSendTask.status == "queued")
        .values(status="cancelled", next_attempt_at=None, updated_at=now)
    )
    return int(result.rowcount or 0)


def retry_kindle_task(db: Session, task_id: str, now: datetime) -> None:
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(
            status="queued",
            attempt_count=0,
            next_attempt_at=None,
            error_message=None,
            started_at=None,
            sent_at=None,
            message_id=None,
            updated_at=now,
        )
    )


def delete_kindle_send_task(db: Session, task_id: str) -> None:
    db.execute(delete(KindleSendTask).where(KindleSendTask.id == task_id))


def next_queued_kindle_task(db: Session, now_ms: int) -> dict[str, Any] | None:
    cutoff = timestamp_ms_to_datetime(now_ms) or datetime.now(UTC)
    task = db.execute(
        select(KindleSendTask)
        .where(
            KindleSendTask.status == "queued",
            or_(
                KindleSendTask.next_attempt_at.is_(None),
                KindleSendTask.next_attempt_at <= cutoff,
            ),
        )
        .order_by(KindleSendTask.created_at.asc(), KindleSendTask.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_record(task) if task is not None else None


def claim_kindle_send_task(
    db: Session, task_id: str, now: datetime
) -> dict[str, Any] | None:
    task = execute_kindle_send_task_update(
        db,
        prepare_claim_kindle_send_task(task_id, now=now),
    )
    return entity_record(task) if task is not None else None


def prepare_claim_kindle_send_task(task_id: str, *, now: datetime) -> Update:
    return (
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id, KindleSendTask.status == "queued")
        .values(
            status="sending",
            started_at=now,
            next_attempt_at=None,
            updated_at=now,
            attempt_count=KindleSendTask.attempt_count + 1,
        )
        .returning(KindleSendTask)
    )


def execute_kindle_send_task_update(
    db: Session,
    statement: Update,
) -> KindleSendTask | None:
    return db.execute(statement).scalar_one_or_none()


def update_kindle_send_snapshot(
    db: Session,
    task_id: str,
    *,
    sender_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_security: str,
    smtp_username: str | None,
    message_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    task = execute_kindle_send_task_update(
        db,
        prepare_kindle_send_snapshot_update(
            task_id,
            sender_email=sender_email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_security=smtp_security,
            smtp_username=smtp_username,
            message_id=message_id,
            now=now,
        ),
    )
    return entity_record(task) if task is not None else None


def prepare_kindle_send_snapshot_update(
    task_id: str,
    *,
    sender_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_security: str,
    smtp_username: str | None,
    message_id: str,
    now: datetime,
) -> Update:
    return (
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(
            sender_email=sender_email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_security=smtp_security,
            smtp_username=smtp_username,
            message_id=message_id,
            updated_at=now,
        )
        .returning(KindleSendTask)
    )


def schedule_kindle_retry(
    db: Session,
    task_id: str,
    *,
    retry_at: datetime,
    error_message: str,
    now: datetime,
) -> None:
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(
            status="queued",
            next_attempt_at=retry_at,
            error_message=error_message,
            updated_at=now,
        )
    )


def mark_kindle_task_failed(
    db: Session,
    task_id: str,
    *,
    error_message: str,
    now: datetime,
) -> None:
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(status="failed", error_message=error_message, updated_at=now)
    )


def mark_kindle_task_sent(db: Session, task_id: str, sent_at: datetime) -> None:
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(status="sent", sent_at=sent_at, error_message=None, updated_at=sent_at)
    )


def list_sending_kindle_tasks(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(select(KindleSendTask).where(KindleSendTask.status == "sending"))
        .scalars()
        .all()
    )
    return [entity_record(row) for row in rows]


def mark_kindle_task_unknown(
    db: Session,
    task_id: str,
    *,
    error_message: str,
    now: datetime,
) -> None:
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.id == task_id)
        .values(status="unknown", error_message=error_message, updated_at=now)
    )


def mark_kindle_tasks_unknown(
    db: Session,
    task_ids: tuple[str, ...],
    *,
    error_message: str,
    now: datetime,
) -> None:
    """Mark interrupted sends with bounded set-based updates."""

    for task_id_chunk in sqlite_parameter_chunks(
        task_ids,
        parameters_per_row=1,
        fixed_parameters=3,
    ):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.id.in_(task_id_chunk))
            .values(status="unknown", error_message=error_message, updated_at=now)
        )


def get_library_asset_for_kindle(db: Session, asset_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(
            LibraryResourceAsset,
            LibraryReadableResource.book_id.label("bookId"),
            LibraryReadableResource.format.label("resourceFormat"),
            LibrarySourceNode.relative_path.label("sourcePath"),
            LibrarySourceNode.observed_size_bytes.label("sizeBytes"),
        )
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryResourceAsset.resource_id,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .where(LibraryResourceAsset.id == asset_id)
    ).first()
    if row is None:
        return None
    file_row = entity_record(row[0])
    file_row["bookId"] = row.bookId
    file_row["resourceFormat"] = row.resourceFormat
    file_row["sourcePath"] = row.sourcePath
    file_row["sizeBytes"] = int(row.sizeBytes or 0)
    return file_row


def get_library_asset_details_for_kindle(
    db: Session, asset_id: str
) -> dict[str, Any] | None:
    row = db.execute(
        select(
            LibraryResourceAsset,
            LibraryReadableResource.book_id.label("bookId"),
            LibraryReadableResource.format.label("resourceFormat"),
            LibraryBookMetadata.title.label("bookTitle"),
            LibraryReadableResourceMetadata.title.label("resourceTitle"),
            LibrarySourceNode.relative_path.label("sourcePath"),
            LibrarySourceNode.observed_size_bytes.label("sizeBytes"),
        )
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryResourceAsset.resource_id,
        )
        .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .join(
            LibraryReadableResourceMetadata,
            LibraryReadableResourceMetadata.resource_id == LibraryReadableResource.id,
        )
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
        )
        .where(LibraryResourceAsset.id == asset_id)
    ).first()
    if row is None:
        return None
    file_row = entity_record(row[0])
    file_row["bookId"] = row.bookId
    file_row["resourceFormat"] = row.resourceFormat
    file_row["bookTitle"] = row.bookTitle
    file_row["resourceTitle"] = row.resourceTitle
    file_row["sourcePath"] = row.sourcePath
    file_row["sizeBytes"] = int(row.sizeBytes or 0)
    return file_row
