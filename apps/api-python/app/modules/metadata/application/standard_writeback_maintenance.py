"""Release expired recovery space only after verified backup cleanup."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.metadata.application.standard_writeback import (
    PreparedStandardFile,
    StandardWriteFile,
    StandardWritePlan,
)


class StandardBackupStore(Protocol):
    def expired_backups(
        self, now_ms: int
    ) -> tuple[tuple[str, int, StandardWritePlan, PreparedStandardFile], ...]: ...
    def backup_cleanup_result(
        self, operation_id: str, ordinal: int, now_ms: int, *, failed: bool
    ) -> None: ...


class StandardBackupFiles(Protocol):
    def clear_backup(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> None: ...


class StandardBackupUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class MaintainStandardBackups:
    store: StandardBackupStore
    files: StandardBackupFiles
    uow: StandardBackupUnitOfWork
    clock_ms: Callable[[], int]

    def execute(self) -> None:
        entries = self.store.expired_backups(self.clock_ms())
        self.uow.rollback()
        for operation_id, ordinal, plan, proof in entries:
            try:
                self.files.clear_backup(plan.targets[ordinal].file, proof)
            except Exception:  # noqa: BLE001 - retain evidence and retry; never delete an unverified file.
                failed = True
            else:
                failed = False
            self.store.backup_cleanup_result(
                operation_id, ordinal, self.clock_ms(), failed=failed
            )
            self.uow.commit()
