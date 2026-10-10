"""Single-consumer iteration for durable system file moves."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.contracts.diagnostics import FailureDiagnostics
from app.core.exception_diagnostics import capture_exception
from app.modules.library.application.execute_file_moves import (
    ExecuteFileMoveOperation,
    MoveExecutionUnitOfWork,
)


class MoveWorkerStore(Protocol):
    def next_recovery(self, after: str) -> str | None: ...
    def interrupted_targets(self, operation_id: str) -> tuple[tuple[int, str], ...]: ...
    def prepare_recovery(self, operation_id: str, now_ms: int) -> None: ...
    def claim_next(self, now_ms: int) -> str | None: ...


@dataclass
class FileMoveWorker:
    store: MoveWorkerStore
    execute: ExecuteFileMoveOperation
    uow: MoveExecutionUnitOfWork
    clock_ms: Callable[[], int]
    diagnostics: FailureDiagnostics
    recovery_cursor: str = ""
    recovered: bool = False

    def process_once(self) -> bool:
        operation_id: str | None = None
        try:
            if not self.recovered:
                operation_id = self.store.next_recovery(self.recovery_cursor)
                if operation_id is not None:
                    # A failure stays visible for manual recovery or the next process
                    # start. Never retry an uncertain publication in a hot loop.
                    interrupted = self.store.interrupted_targets(operation_id)
                    diagnostics = [
                        self.diagnostics.prepare(
                            InterruptedMoveResultUnavailable(
                                f"Target was already {stage} at recovery start; "
                                "the previous move result was not provided"
                            ),
                            event="file_move.previous_result_unavailable",
                        )
                        for ordinal, stage in interrupted
                    ]
                    try:
                        self.uow.rollback()
                    finally:
                        for diagnostic in diagnostics:
                            self.diagnostics.persist(diagnostic)
                    self.store.prepare_recovery(operation_id, self.clock_ms())
                    self.uow.commit()
                    self.recovery_cursor = operation_id
                    return True
                self.recovered = True
                self.uow.rollback()
            operation_id = self.store.claim_next(self.clock_ms())
            self.uow.commit()
            if operation_id is not None:
                self.execute.execute(operation_id)
                return True
            return False
        except Exception as error:
            capture_exception(error, persist=False)
            diagnostic = self.diagnostics.prepare(
                error,
                event="file_move.worker_failed",
            )
            try:
                self.uow.rollback()
            except Exception as rollback_error:
                capture_exception(rollback_error, persist=False)
                secondary = self.diagnostics.prepare(
                    rollback_error,
                    event="file_move.worker_rollback_failed",
                )
                self.diagnostics.persist(secondary)
                raise
            finally:
                self.diagnostics.persist(diagnostic)
            raise


class InterruptedMoveResultUnavailable(Exception):
    """Observed unfinished persisted stage with no historical execution result."""
