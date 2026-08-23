"""ORM persistence for download queue and executor."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, update
from sqlalchemy.orm import Mapper, Session
from sqlalchemy.sql.dml import Update

from app.models.common import db_timestamp
from app.models.import_pipeline import DownloadTask
from app.models.library import Library
from app.models.settings import SystemSetting


def entity_record(entity: object) -> dict[str, Any]:
    """Return a queue row as a transport-neutral column record."""

    inspection = sa_inspect(entity)
    mapper = cast(Mapper[Any], getattr(inspection, "mapper", inspection))
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = cast(Mapper[Any], sa_inspect(model))
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


ACTIVE_DOWNLOAD_STATUSES = ("queued", "downloading", "downloaded", "completed")


def get_download_task(db: Session, task_id: str) -> dict[str, Any] | None:
    task = db.get(DownloadTask, task_id)
    return entity_record(task) if task is not None else None


def next_queued_download_task(db: Session) -> dict[str, Any] | None:
    task = db.execute(
        select(DownloadTask)
        .where(DownloadTask.status == "queued")
        .order_by(DownloadTask.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_record(task) if task is not None else None


def prepare_mark_download_task_importing(
    task_id: str,
    *,
    updated_at: object,
) -> Update:
    return (
        update(DownloadTask)
        .where(DownloadTask.id == task_id)
        .values(status="importing", updated_at=updated_at)
    )


def mark_download_task_importing(
    db: Session,
    task_id: str,
    *,
    updated_at: object | None = None,
) -> None:
    db.execute(
        prepare_mark_download_task_importing(
            task_id,
            updated_at=updated_at or db_timestamp(),
        )
    )


def prepare_claim_download_task(task_id: str, *, now: object) -> Update:
    return (
        update(DownloadTask)
        .where(
            DownloadTask.id == task_id,
            DownloadTask.status.in_(("queued", "failed", "PENDING", "FAILED")),
        )
        .values(
            status="downloading",
            progress=1,
            error_message=None,
            updated_at=now,
        )
        .returning(DownloadTask)
    )


def execute_download_task_row_update(
    db: Session,
    statement: Update,
) -> DownloadTask | None:
    return db.execute(statement).scalar_one_or_none()


def claim_download_task(
    db: Session, task_id: str, *, now: Any
) -> dict[str, Any] | None:
    statement = prepare_claim_download_task(task_id, now=now)
    task = execute_download_task_row_update(db, statement)
    return entity_record(task) if task is not None else None


def prepare_download_task_state_update(
    task_id: str,
    values: dict[str, object],
) -> Update:
    name_to_attr = _legacy_column_to_attr(DownloadTask)
    patch = {
        attr: value
        for key, value in values.items()
        if (attr := name_to_attr.get(key)) is not None
    }
    return (
        update(DownloadTask)
        .where(DownloadTask.id == task_id)
        .values(**patch)
        .returning(DownloadTask)
    )


def update_download_task(
    db: Session,
    task_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    statement = prepare_download_task_state_update(task_id, values)
    task = execute_download_task_row_update(db, statement)
    return entity_record(task) if task is not None else None


def find_active_download_task(db: Session, record_id: str) -> dict[str, Any] | None:
    task = db.execute(
        select(DownloadTask)
        .where(
            DownloadTask.search_record_id == record_id,
            DownloadTask.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
        .order_by(DownloadTask.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_record(task) if task is not None else None


def system_setting_value(db: Session, key: str) -> str | None:
    row = db.get(SystemSetting, key)
    return row.value if row is not None else None


def list_enabled_libraries(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(Library).where(Library.enabled.is_(True))).scalars().all()
    return [entity_record(row) for row in rows]
