"""Application boundary for an already validated backup restore plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.sql.base import Executable


class BackupRecordValidationError(ValueError):
    """An exported record cannot be represented by the current schema."""


@dataclass(frozen=True, slots=True)
class PreparedRestorePlan:
    statements: tuple[Executable, ...]
    restored_counts: dict[str, int]


class BackupRestoreWriter(Protocol):
    def apply(self, plan: PreparedRestorePlan) -> None: ...


class BackupRestoreUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ApplyValidatedBackupRestore:
    """Execute only preconstructed typed SQL inside the live write interval."""

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
        except Exception:
            self._unit_of_work.rollback()
            raise
