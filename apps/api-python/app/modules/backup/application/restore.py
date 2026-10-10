"""Application boundary for an already validated backup restore plan."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.core.exception_diagnostics import capture_exception, record_exception


class BackupRecordValidationError(ValueError):
    """An exported record cannot be represented by the current schema."""


@dataclass(frozen=True, slots=True)
class RestoreTableBatch:
    export_key: str
    table_name: str
    records: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class MaintenanceStateChange:
    setting_key: str
    setting_value: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class PreparedRestorePlan:
    kind: Literal["database", "maintenance"]
    restored_counts: dict[str, int]
    delete_order: tuple[str, ...] = ()
    batches: tuple[RestoreTableBatch, ...] = ()
    maintenance_setting_key: str | None = None
    maintenance_change: MaintenanceStateChange | None = None


class BackupRestoreWriter(Protocol):
    def apply(self, plan: PreparedRestorePlan) -> None: ...


class BackupRestoreUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ApplyValidatedBackupRestore:
    """Apply an immutable validated restore plan in one explicit transaction."""

    def __init__(
        self,
        writer: BackupRestoreWriter,
        unit_of_work: BackupRestoreUnitOfWork,
    ) -> None:
        self._writer = writer
        self._unit_of_work = unit_of_work

    def execute(self, plan: PreparedRestorePlan) -> None:
        try:
            self._writer.apply(plan)
            self._unit_of_work.commit()
        except Exception as error:
            capture_exception(error, persist=False)
            record_exception(
                logging.getLogger(__name__),
                "backup.transaction.failed",
                error,
            )
            try:
                self._unit_of_work.rollback()
            except Exception as rollback_error:  # noqa: BLE001 - preserve both failures at the rollback boundary.
                capture_exception(rollback_error, persist=False)
                record_exception(
                    logging.getLogger(__name__),
                    "backup.transaction.rollback_failed",
                    rollback_error,
                )
                raise ExceptionGroup(
                    "Backup transaction and rollback failed", [error, rollback_error]
                ) from error
            raise
