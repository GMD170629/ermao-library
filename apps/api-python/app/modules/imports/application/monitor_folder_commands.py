"""Prepared commands for monitor-folder state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedMonitorFolderCreate:
    values: dict[str, object]
    event: PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedMonitorFolderUpdate:
    folder_id: str
    values: dict[str, object]
    event: PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedMonitorFolderDelete:
    folder_id: str
    affected_user_ids: tuple[str, ...]
    updated_at: datetime
    event: PreparedSystemEvent


class MonitorFolderWriteStore(Protocol):
    def create(self, prepared: PreparedMonitorFolderCreate) -> None: ...

    def update(self, prepared: PreparedMonitorFolderUpdate) -> None: ...

    def delete(self, prepared: PreparedMonitorFolderDelete) -> bool: ...


def prepare_monitor_folder_update_values(
    values: dict[str, object],
) -> dict[str, object]:
    mapping = {
        "name": "name",
        "rootPath": "root_path",
        "enabled": "enabled",
        "mediaKindPolicy": "media_kind_policy",
        "ignorePatterns": "ignore_patterns",
        "ignoreHidden": "ignore_hidden",
        "minFileSizeBytes": "min_file_size_bytes",
        "description": "description",
        "updatedAt": "updated_at",
    }
    return {
        target: value
        for key, value in values.items()
        if (target := mapping.get(key)) is not None
    }


def persist_monitor_folder_create(
    store: MonitorFolderWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedMonitorFolderCreate,
) -> None:
    try:
        store.create(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def persist_monitor_folder_update(
    store: MonitorFolderWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedMonitorFolderUpdate,
) -> None:
    try:
        store.update(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def persist_monitor_folder_delete(
    store: MonitorFolderWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedMonitorFolderDelete,
) -> bool:
    try:
        deleted = store.delete(prepared)
        unit_of_work.commit()
        return deleted
    except Exception:
        unit_of_work.rollback()
        raise
