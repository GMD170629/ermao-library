"""Prepared atomic commands for import HTTP maintenance writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedTerminalImportClear:
    task_ids: tuple[str, ...]
    events: tuple[PreparedSystemEvent, ...]


@dataclass(frozen=True, slots=True)
class PreparedImportRetry:
    task_id: str
    updated_at: datetime
    work_row: dict[str, object]
    event: PreparedSystemEvent


class ImportMaintenanceWriteStore(Protocol):
    def clear_terminal(self, prepared: PreparedTerminalImportClear) -> int: ...

    def retry(self, prepared: PreparedImportRetry) -> None: ...


def prepare_import_retry(
    *,
    task_id: str,
    source_path: Path,
    updated_at: datetime,
    event: PreparedSystemEvent,
) -> PreparedImportRetry:
    source_key = sha256(str(source_path).encode("utf-8")).hexdigest()
    return PreparedImportRetry(
        task_id=task_id,
        updated_at=updated_at,
        work_row={
            "id": f"work_{uuid4().hex}",
            "kind": "IMPORT_SOURCE",
            "scanJobId": None,
            "importTaskId": task_id,
            "dedupeKey": f"import:{source_key}:{task_id}",
            "status": "PENDING",
            "priority": 10,
            "availableAt": updated_at,
            "attempts": 0,
            "createdAt": updated_at,
            "updatedAt": updated_at,
        },
        event=event,
    )


def persist_terminal_import_clear(
    store: ImportMaintenanceWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedTerminalImportClear,
) -> int:
    try:
        deleted = store.clear_terminal(prepared)
        unit_of_work.commit()
        return deleted
    except Exception:
        unit_of_work.rollback()
        raise


def persist_import_retry(
    store: ImportMaintenanceWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedImportRetry,
) -> None:
    try:
        store.retry(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
