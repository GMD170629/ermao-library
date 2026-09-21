"""Single-consumer iteration for durable moves and expired recovery copies."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.library.application.execute_file_moves import (
    ExecuteFileMoveOperation,
    MoveExecutionUnitOfWork,
)
from app.modules.library.application.file_move_recovery_cleanup import (
    CleanExpiredMoveBackups,
)


class MoveWorkerStore(Protocol):
    def next_recovery(self, after: str) -> str | None: ...
    def prepare_recovery(self, operation_id: str, now_ms: int) -> None: ...
    def claim_next(self, now_ms: int) -> str | None: ...


@dataclass
class FileMoveWorker:
    store: MoveWorkerStore
    execute: ExecuteFileMoveOperation
    cleanup: CleanExpiredMoveBackups
    uow: MoveExecutionUnitOfWork
    clock_ms: Callable[[], int]
    recovery_cursor: str = ""
    recovered: bool = False
    next_cleanup_at: int = 0

    def process_once(self) -> bool:
        if not self.recovered:
            operation_id = self.store.next_recovery(self.recovery_cursor)
            if operation_id is not None:
                # A failure stays visible for manual recovery or the next process
                # start. Never retry an uncertain publication in a hot loop.
                self.recovery_cursor = operation_id
                self.store.prepare_recovery(operation_id, self.clock_ms())
                self.uow.commit()
                self.execute.execute(operation_id)
                return True
            self.recovered = True
            self.uow.rollback()
        operation_id = self.store.claim_next(self.clock_ms())
        self.uow.commit()
        if operation_id is not None:
            self.execute.execute(operation_id)
            return True
        now = self.clock_ms()
        if now >= self.next_cleanup_at:
            self.next_cleanup_at = now + 60_000
            return self.cleanup.execute() > 0
        return False
