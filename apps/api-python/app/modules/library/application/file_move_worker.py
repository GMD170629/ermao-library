"""Single-consumer iteration for durable system file moves."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.contracts.diagnostics import FailureDiagnostics
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
        parent_diagnostic_id: str | None = None
        step = "recover_operations"
        try:
            if not self.recovered:
                step = "select_recovery"
                operation_id = self.store.next_recovery(self.recovery_cursor)
                if operation_id is not None:
                    # A failure stays visible for manual recovery or the next process
                    # start. Never retry an uncertain publication in a hot loop.
                    step = "inspect_recovery_state"
                    interrupted = self.store.interrupted_targets(operation_id)
                    diagnostics = [
                        self.diagnostics.prepare(
                            InterruptedMoveResultUnavailable(
                                f"Target was already {stage} at recovery start; "
                                "the previous move result was not provided"
                            ),
                            event="file_move.previous_result_unavailable",
                            context={
                                "operation_id": operation_id,
                                "target_ordinal": ordinal,
                                "stage": stage,
                                "step": step,
                            },
                        )
                        for ordinal, stage in interrupted
                    ]
                    if diagnostics:
                        parent_diagnostic_id = diagnostics[0].diagnostic_id
                    step = "release_recovery_snapshot"
                    try:
                        self.uow.rollback()
                    finally:
                        for diagnostic in diagnostics:
                            self.diagnostics.persist(diagnostic)
                    parent_diagnostic_id = None
                    step = "prepare_recovery"
                    self.store.prepare_recovery(operation_id, self.clock_ms())
                    self.uow.commit()
                    self.recovery_cursor = operation_id
                    return True
                self.recovered = True
                self.uow.rollback()
            step = "claim_operation"
            operation_id = self.store.claim_next(self.clock_ms())
            self.uow.commit()
            if operation_id is not None:
                step = "execute_operation"
                self.execute.execute(operation_id)
                return True
            return False
        except Exception as error:
            diagnostic = self.diagnostics.prepare(
                error,
                event="file_move.worker_failed",
                context={
                    "operation_id": operation_id,
                    "step": step,
                    "parent_diagnostic_id": parent_diagnostic_id,
                },
            )
            try:
                self.uow.rollback()
            except Exception as rollback_error:
                secondary = self.diagnostics.prepare(
                    rollback_error,
                    event="file_move.worker_rollback_failed",
                    context={
                        "operation_id": operation_id,
                        "step": "rollback",
                        "parent_diagnostic_id": diagnostic.diagnostic_id,
                    },
                )
                self.diagnostics.persist(secondary)
                raise
            finally:
                self.diagnostics.persist(diagnostic)
            raise


class InterruptedMoveResultUnavailable(Exception):
    """Observed unfinished persisted stage with no historical execution result."""
