"""ORM persistence for Kindle send queue and HTTP routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import MetaData, Table, delete, func, inspect as sa_inspect, or_, select, update
from sqlalchemy.orm import Session

from app.core.time import timestamp_ms_to_datetime
from app.models.import_pipeline import KindleSendTask
from app.models.library import LibraryEdition, LibraryFile, LibraryVolume, LibraryWork
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


def _legacy_table(db: Session, table_name: str) -> Table | None:
    if not has_table(db, table_name):
        return None
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=db.connection())


def has_table(db: Session, table: str) -> bool:
    try:
        return sa_inspect(db.connection()).has_table(table)
    except Exception:
        return False


def get_kindle_send_task(db: Session, task_id: str) -> dict[str, Any] | None:
    if not has_table(db, "KindleSendTask"):
        return None
    task = db.get(KindleSendTask, task_id)
    return entity_as_legacy_dict(task) if task is not None else None


def list_kindle_send_tasks(
    db: Session,
    *,
    user_id: str,
    status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    if not has_table(db, "KindleSendTask"):
        return [], 0
    filters = [KindleSendTask.user_id == user_id]
    if status:
        filters.append(KindleSendTask.status == status)
    total = int(
        db.scalar(select(func.count()).select_from(KindleSendTask).where(*filters)) or 0
    )
    rows = db.execute(
        select(KindleSendTask)
        .where(*filters)
        .order_by(KindleSendTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows], total


def find_active_kindle_task(
    db: Session,
    *,
    file_id: str,
    recipient_email: str,
    exclude_task_id: str | None = None,
) -> dict[str, Any] | None:
    if not has_table(db, "KindleSendTask"):
        return None
    filters = [
        KindleSendTask.file_id == file_id,
        KindleSendTask.recipient_email == recipient_email,
        KindleSendTask.status.in_(("queued", "sending")),
    ]
    if exclude_task_id:
        filters.append(KindleSendTask.id != exclude_task_id)
    task = db.execute(
        select(KindleSendTask).where(*filters).order_by(KindleSendTask.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    return entity_as_legacy_dict(task) if task is not None else None


def create_kindle_send_task(db: Session, values: dict[str, Any]) -> KindleSendTask:
    name_to_attr = _legacy_column_to_attr(KindleSendTask)
    payload = {name_to_attr[key]: value for key, value in values.items() if key in name_to_attr}
    task = KindleSendTask(**payload)
    db.add(task)
    db.flush()
    return task


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
    if not has_table(db, "KindleSendTask"):
        return None
    cutoff = timestamp_ms_to_datetime(now_ms) or datetime.now(timezone.utc)
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
    return entity_as_legacy_dict(task) if task is not None else None


def claim_kindle_send_task(db: Session, task_id: str, now: datetime) -> dict[str, Any] | None:
    table = _legacy_table(db, "KindleSendTask")
    if table is None:
        return None
    values: dict[str, Any] = {
        "status": "sending",
        "startedAt": now,
        "nextAttemptAt": None,
        "updatedAt": now,
    }
    if "attemptCount" in table.c:
        values["attemptCount"] = table.c.attemptCount + 1
    result = db.execute(
        update(table).where(table.c.id == task_id, table.c.status == "queued").values(**values)
    )
    if int(result.rowcount or 0) != 1:
        return None
    db.flush()
    return get_kindle_send_task(db, task_id)


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
    db.execute(
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
    )
    db.flush()
    return get_kindle_send_task(db, task_id)


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
    if not has_table(db, "KindleSendTask"):
        return []
    rows = db.execute(
        select(KindleSendTask).where(KindleSendTask.status == "sending")
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]


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


def get_library_file_for_kindle(db: Session, file_id: str) -> dict[str, Any] | None:
    if not has_table(db, "LibraryFile"):
        return None
    row = db.execute(
        select(
            LibraryFile,
            LibraryEdition.work_id.label("workId"),
            LibraryEdition.format.label("editionFormat"),
        )
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .where(LibraryFile.id == file_id)
    ).first()
    if row is None:
        return None
    file_row = entity_as_legacy_dict(row[0])
    file_row["workId"] = row.workId
    file_row["editionFormat"] = row.editionFormat
    return file_row


def get_library_file_details_for_kindle(db: Session, file_id: str) -> dict[str, Any] | None:
    if not has_table(db, "LibraryFile"):
        return None
    row = db.execute(
        select(
            LibraryFile,
            LibraryEdition.work_id.label("workId"),
            LibraryEdition.format.label("editionFormat"),
            LibraryEdition.version_name.label("versionName"),
            LibraryWork.title.label("bookTitle"),
            LibraryVolume.title.label("volumeTitle"),
        )
        .join(LibraryEdition, LibraryEdition.id == LibraryFile.edition_id)
        .join(LibraryWork, LibraryWork.id == LibraryEdition.work_id)
        .outerjoin(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .where(LibraryFile.id == file_id)
    ).first()
    if row is None:
        return None
    file_row = entity_as_legacy_dict(row[0])
    file_row["workId"] = row.workId
    file_row["editionFormat"] = row.editionFormat
    file_row["versionName"] = row.versionName
    file_row["bookTitle"] = row.bookTitle
    file_row["volumeTitle"] = row.volumeTitle
    return file_row
