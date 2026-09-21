"""Advance durable file moves through publication and index reconciliation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.contracts.source_relocation import SourceRelocation
from app.modules.library.application.file_move_operations import require_plan_access
from app.modules.library.application.file_move_plans import (
    FileMovePlan,
    MoveActor,
    PlannedMove,
)
from app.modules.library.domain.file_moves import FileMoveError


@dataclass(frozen=True)
class MoveExecution:
    plan: FileMovePlan
    stages: tuple[str, ...]
    cancelled: bool


class MoveExecutionStore(Protocol):
    def execution(self, operation_id: str) -> MoveExecution: ...
    def checkpoint(
        self,
        operation_id: str,
        ordinal: int,
        stage: str,
        now_ms: int,
        error_code: str | None = None,
    ) -> None: ...
    def finish(self, operation_id: str, now_ms: int) -> None: ...


class MovePublicationPort(Protocol):
    def validate(self, move: PlannedMove) -> None: ...
    def publish(self, move: PlannedMove) -> None: ...
    def is_published(self, move: PlannedMove) -> bool: ...


class MoveIndexPort(Protocol):
    def apply(self, move: PlannedMove, now: datetime) -> tuple[str, ...]: ...


class MoveExecutionUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class ExecuteFileMoveOperation:
    store: MoveExecutionStore
    files: MovePublicationPort
    index: MoveIndexPort
    authorize: Callable[[MoveActor], MoveActor]
    reconcile_imports: Callable[[SourceRelocation], None]
    discard_writebacks: Callable[[SourceRelocation], int]
    uow: MoveExecutionUnitOfWork
    clock_ms: Callable[[], int]
    clock: Callable[[], datetime]

    def execute(self, operation_id: str) -> None:
        execution = self.store.execution(operation_id)
        self.uow.rollback()  # Read snapshot released before filesystem validation.
        plan = execution.plan
        # A newly claimed request must preflight all targets before any publication.
        if (
            all(stage == "QUEUED" for stage in execution.stages)
            and not execution.cancelled
        ):
            try:
                require_plan_access(plan, self.authorize(plan.actor))
                self.uow.rollback()
                for move in plan.moves:
                    self.files.validate(move)
            except FileMoveError as error:
                self.uow.rollback()
                for index in range(len(plan.moves)):
                    self.store.checkpoint(
                        operation_id, index, "FAILED", self.clock_ms(), str(error)
                    )
                self.store.finish(operation_id, self.clock_ms())
                self.uow.commit()
                return
        for ordinal, move in enumerate(plan.moves):
            current = self.store.execution(operation_id)
            stage = current.stages[ordinal]
            self.uow.rollback()
            if stage in {"COMPLETED", "FAILED", "CANCELLED"}:
                continue
            if stage == "RECOVERY_REQUIRED":
                return
            publication_uncertain = stage != "QUEUED"
            try:
                if stage == "QUEUED":
                    if current.cancelled:
                        self.store.checkpoint(
                            operation_id, ordinal, "CANCELLED", self.clock_ms()
                        )
                        self.uow.commit()
                        continue
                    require_plan_access(plan, self.authorize(plan.actor))
                    self.uow.rollback()
                    self.files.validate(move)
                    self.store.checkpoint(
                        operation_id, ordinal, "PREPARING", self.clock_ms()
                    )
                    self.uow.commit()
                    stage = "PREPARING"
                if stage == "PREPARING":
                    # Reopening an uncertain rename observes only the frozen source
                    # and target. A published item receives minimal index repair,
                    # even if its token has since been revoked.
                    published = self.files.is_published(move)
                    publication_uncertain = published
                    if not published:
                        require_plan_access(plan, self.authorize(plan.actor))
                        cancelled = self.store.execution(operation_id).cancelled
                        self.uow.rollback()
                        if cancelled:
                            self.store.checkpoint(
                                operation_id, ordinal, "CANCELLED", self.clock_ms()
                            )
                            self.uow.commit()
                            continue
                        publication_uncertain = True
                        self.files.publish(move)
                    self.store.checkpoint(
                        operation_id, ordinal, "FILES_PUBLISHED", self.clock_ms()
                    )
                    self.uow.commit()
                    stage = "FILES_PUBLISHED"
                if stage == "FILES_PUBLISHED":
                    if not self.files.is_published(move):
                        raise FileMoveError("PUBLISHED_FILE_MISSING")
                    node_ids = self.index.apply(move, self.clock())
                    change = SourceRelocation(
                        move.source.library_id,
                        move.source.relative_path,
                        move.destination.library_id,
                        move.destination.relative_path,
                        node_ids,
                        move.source.book_ids,
                    )
                    self.discard_writebacks(change)
                    self.reconcile_imports(change)
                    self.store.checkpoint(
                        operation_id, ordinal, "INDEX_UPDATED", self.clock_ms()
                    )
                    self.uow.commit()
                self.store.checkpoint(
                    operation_id, ordinal, "COMPLETED", self.clock_ms()
                )
                self.uow.commit()
            except FileMoveError as error:
                self.uow.rollback()
                state = "RECOVERY_REQUIRED" if publication_uncertain else "FAILED"
                self.store.checkpoint(
                    operation_id, ordinal, state, self.clock_ms(), str(error)
                )
                if state == "FAILED":
                    remaining = self.store.execution(operation_id)
                    for pending, pending_stage in enumerate(remaining.stages):
                        if pending_stage == "QUEUED":
                            self.store.checkpoint(
                                operation_id, pending, "CANCELLED", self.clock_ms()
                            )
                self.store.finish(operation_id, self.clock_ms())
                self.uow.commit()
                return
            except Exception:
                self.uow.rollback()
                self.store.checkpoint(
                    operation_id,
                    ordinal,
                    "RECOVERY_REQUIRED",
                    self.clock_ms(),
                    "FILE_OPERATION_INTERRUPTED",
                )
                self.store.finish(operation_id, self.clock_ms())
                self.uow.commit()
                raise
        self.store.finish(operation_id, self.clock_ms())
        self.uow.commit()
