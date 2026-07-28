"""ORM persistence for user administration routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, inspect as sa_inspect, select, update
from sqlalchemy.orm import Session

from app.models.auth import (
    PasswordResetToken,
    ReaderBookmark,
    Session as UserSession,
    UserMonitorFolderAccess,
    UserPreference,
)
from app.models.import_pipeline import KindleSendTask
from app.models.library import (
    LibraryConsumptionState,
    LibraryOperation,
    LibraryReadingProgress,
    WorkDetailPreference,
)
from app.models.settings import ReaderBookPreference, ReaderPreference, ReaderProgressCursor, SystemEvent
from app.models.shelf import Shelf, ShelfWork


def list_monitor_folder_ids(db: Session, user_id: str) -> list[str]:
    rows = db.execute(
        select(UserMonitorFolderAccess.monitor_folder_id)
        .where(UserMonitorFolderAccess.user_id == user_id)
        .order_by(UserMonitorFolderAccess.monitor_folder_id)
    ).scalars()
    return [str(item) for item in rows]


def validate_monitor_folder_ids(db: Session, folder_ids: list[str]) -> list[str]:
    if not folder_ids:
        return []
    from app.models.settings import MonitorFolder

    existing = {
        str(item)
        for item in db.execute(
            select(MonitorFolder.id).where(MonitorFolder.id.in_(folder_ids))
        ).scalars()
    }
    missing = [folder_id for folder_id in folder_ids if folder_id not in existing]
    if missing:
        raise ValueError("包含不存在的监控文件夹")
    return folder_ids


def replace_monitor_folder_access(db: Session, user_id: str, folder_ids: list[str], now: datetime) -> None:
    db.execute(delete(UserMonitorFolderAccess).where(UserMonitorFolderAccess.user_id == user_id))
    for folder_id in folder_ids:
        db.add(
            UserMonitorFolderAccess(
                user_id=user_id,
                monitor_folder_id=folder_id,
                created_at=now,
            )
        )


def delete_personal_user_data(db: Session, user_id: str, anonymous_user_id: str) -> None:
    """Delete account-owned rows even on databases upgraded from pre-FK schemas."""

    tables = set(sa_inspect(db.connection()).get_table_names())
    if {"Shelf", "ShelfWork"}.issubset(tables):
        db.execute(
            delete(ShelfWork).where(
                ShelfWork.shelf_id.in_(select(Shelf.id).where(Shelf.owner_user_id == user_id))
            )
        )
    if "Shelf" in tables:
        db.execute(delete(Shelf).where(Shelf.owner_user_id == user_id))
    for model in (
        ReaderBookmark,
        WorkDetailPreference,
        LibraryConsumptionState,
        LibraryReadingProgress,
        ReaderProgressCursor,
        ReaderBookPreference,
        ReaderPreference,
        UserPreference,
        UserMonitorFolderAccess,
        PasswordResetToken,
        UserSession,
    ):
        if model.__tablename__ in tables:
            db.execute(delete(model).where(model.user_id == user_id))
    for model in (KindleSendTask, LibraryOperation):
        if model.__tablename__ in tables:
            db.execute(update(model).where(model.user_id == user_id).values(user_id=None))
    if "SystemEvent" in tables:
        db.execute(
            update(SystemEvent).where(SystemEvent.actor_id == user_id).values(actor_id=anonymous_user_id)
        )
        db.execute(
            update(SystemEvent).where(SystemEvent.target_id == user_id).values(target_id=anonymous_user_id)
        )
