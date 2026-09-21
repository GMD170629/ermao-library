"""Expire verified recovery copies without touching active or unresolved targets."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.library.application.execute_file_moves import MoveExecutionUnitOfWork
from app.modules.library.application.file_move_plans import (
    PlannedMove,
    PreparedMoveCopy,
    StagedMoveSource,
)
from app.modules.library.application.source_browser import SourceAccessError
from app.modules.library.domain.file_moves import FileMoveError


@dataclass(frozen=True)
class ExpiredMoveBackup:
    operation_id: str
    ordinal: int
    move: PlannedMove
    copy: PreparedMoveCopy
    backup: StagedMoveSource


class MoveBackupStore(Protocol):
    def expired_backups(
        self, now_ms: int, limit: int
    ) -> tuple[ExpiredMoveBackup, ...]: ...
    def clear_backup(self, backup: ExpiredMoveBackup, now_ms: int) -> None: ...
    def retain_backup(
        self, backup: ExpiredMoveBackup, error_code: str, now_ms: int
    ) -> None: ...


class MoveBackupFiles(Protocol):
    def remove_backup(self, backup: ExpiredMoveBackup) -> None: ...


@dataclass(frozen=True)
class CleanExpiredMoveBackups:
    store: MoveBackupStore
    files: MoveBackupFiles
    uow: MoveExecutionUnitOfWork
    clock_ms: Callable[[], int]

    def execute(self) -> int:
        candidates = self.store.expired_backups(self.clock_ms(), 5)
        self.uow.rollback()
        cleaned = 0
        for backup in candidates:
            try:
                self.files.remove_backup(backup)
            except (FileMoveError, SourceAccessError, OSError) as error:
                self.store.retain_backup(
                    backup,
                    str(error)
                    if isinstance(error, FileMoveError)
                    else "BACKUP_CLEANUP_UNAVAILABLE",
                    self.clock_ms(),
                )
                self.uow.commit()
                continue
            self.store.clear_backup(backup, self.clock_ms())
            self.uow.commit()
            cleaned += 1
        return cleaned
