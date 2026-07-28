"""ORM persistence for download queue and executor."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect, select, update
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import DownloadTask
from app.models.settings import MonitorFolder, SystemSetting
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}

ACTIVE_DOWNLOAD_STATUSES = ("queued", "downloading", "downloaded", "completed")


def has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.get_bind()).has_table(table)


def get_download_task(db: Session, task_id: str) -> dict[str, Any] | None:
    if not has_table(db, "DownloadTask"):
        return None
    task = db.get(DownloadTask, task_id)
    return entity_as_legacy_dict(task) if task is not None else None


def next_queued_download_task(db: Session) -> dict[str, Any] | None:
    if not has_table(db, "DownloadTask"):
        return None
    task = db.execute(
        select(DownloadTask)
        .where(DownloadTask.status == "queued")
        .order_by(DownloadTask.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_as_legacy_dict(task) if task is not None else None


def mark_download_task_importing(db: Session, task_id: str) -> None:
    db.execute(
        update(DownloadTask)
        .where(DownloadTask.id == task_id)
        .values(status="importing", updated_at=db_timestamp())
    )


def update_download_task(
    db: Session,
    task_id: str,
    values: dict[str, Any],
) -> dict[str, Any] | None:
    if not has_table(db, "DownloadTask"):
        return None
    task = db.get(DownloadTask, task_id)
    if task is None:
        return None
    name_to_attr = _legacy_column_to_attr(DownloadTask)
    for key, value in values.items():
        attr = name_to_attr.get(key)
        if attr is not None:
            setattr(task, attr, value)
    db.flush()
    return entity_as_legacy_dict(task)


def find_active_download_task(db: Session, record_id: str) -> dict[str, Any] | None:
    if not has_table(db, "DownloadTask"):
        return None
    task = db.execute(
        select(DownloadTask)
        .where(
            DownloadTask.search_record_id == record_id,
            DownloadTask.status.in_(ACTIVE_DOWNLOAD_STATUSES),
        )
        .order_by(DownloadTask.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return entity_as_legacy_dict(task) if task is not None else None


def system_setting_value(db: Session, key: str) -> str | None:
    if not has_table(db, "SystemSetting"):
        return None
    row = db.get(SystemSetting, key)
    return row.value if row is not None else None


def list_enabled_monitor_folders(db: Session) -> list[dict[str, Any]]:
    if not has_table(db, "MonitorFolder"):
        return []
    rows = db.execute(
        select(MonitorFolder).where(MonitorFolder.enabled.is_(True))
    ).scalars().all()
    return [entity_as_legacy_dict(row) for row in rows]
