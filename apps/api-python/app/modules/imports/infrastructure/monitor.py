"""ORM persistence for monitor folders and import path caches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask
from app.models.library import LibraryFile
from app.models.settings import MonitorFolder, SystemSetting
from app.modules.imports.infrastructure.library_queries import (
    add_work_to_shelf,
    audio_bundle_fully_imported,
    get_completed_import_task_for_source,
    shelf_exists,
    touch_shelf_updated_at,
)
from app.models.common import db_timestamp
from app.services.audio_metadata import collect_audio_bundle_files


def list_enabled_monitor_folders(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(MonitorFolder.__table__)
        .where(MonitorFolder.enabled.is_(True))
        .order_by(MonitorFolder.created_at.desc())
    ).mappings().all()
    return [dict(row) for row in rows]


def get_system_settings(db: Session, keys: tuple[str, ...]) -> dict[str, str]:
    rows = db.scalars(select(SystemSetting).where(SystemSetting.key.in_(keys))).all()
    return {row.key: row.value for row in rows}


def upsert_system_setting(db: Session, key: str, value: str) -> None:
    existing = db.get(SystemSetting, key)
    now = db_timestamp()
    if existing is not None:
        db.execute(
            update(SystemSetting).where(SystemSetting.key == key).values(value=value, updated_at=now)
        )
        return
    db.add(SystemSetting(key=key, value=value, created_at=now, updated_at=now))


def add_work_to_target_shelf(
    db: Session,
    *,
    shelf_id: str,
    work_id: str,
) -> None:
    if not shelf_exists(db, shelf_id):
        return
    now = db_timestamp()
    add_work_to_shelf(db, shelf_id, work_id, created_at=now)
    touch_shelf_updated_at(db, shelf_id, updated_at=now)


def get_completed_import_task_work_id(db: Session, source_path: str) -> dict[str, Any] | None:
    return get_completed_import_task_for_source(db, source_path)


def load_known_import_paths(db: Session) -> set[Path]:
    rows: list[str] = []
    task_rows = db.execute(
        select(ImportTask.source_path, ImportTask.task_kind).where(
            ImportTask.source_path.is_not(None)
        )
    ).all()
    for source_path, task_kind in task_rows:
        candidate = Path(str(source_path)).expanduser().resolve()
        directory_task = str(task_kind or "").upper() == "AUDIO_BUNDLE"
        if directory_task and candidate.is_dir() and not audio_bundle_fully_imported(
            db,
            [str(item.resolve()) for item in collect_audio_bundle_files(candidate)],
        ):
            continue
        rows.append(str(candidate))
    rows.extend(
        str(value)
        for value in db.scalars(
            select(LibraryFile.path).where(LibraryFile.path.is_not(None))
        ).all()
        if value
    )
    return {Path(source_path).expanduser().resolve() for source_path in rows if source_path}
