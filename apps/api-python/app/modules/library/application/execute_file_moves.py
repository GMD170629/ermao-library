"""Advance durable file moves through publication and index reconciliation."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.contracts.source_relocation import SourceRelocation
from app.modules.library.application.file_move_operations import require_plan_access
from app.modules.library.application.file_move_plans import (
    CreatedMoveDirectory,
    DestinationInspection,
    FileMovePlan,
    MoveActor,
    PlannedMove,
    PreparedMoveCopy,
    StagedMoveSource,
)
from app.modules.library.domain.file_moves import FileIdentity, FileMoveError


@dataclass(frozen=True)
class MoveExecution:
    plan: FileMovePlan
    stages: tuple[str, ...]
    cancelled: bool
    created_directories: tuple[tuple[CreatedMoveDirectory, ...], ...]
    copies: tuple[PreparedMoveCopy | None, ...]


class MoveExecutionStore(Protocol):
    def record_copy(
        self, operation_id: str, ordinal: int, copy: PreparedMoveCopy
    ) -> None: ...
    def record_source_backup(
        self, operation_id: str, ordinal: int, backup: StagedMoveSource, now_ms: int
    ) -> None: ...
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
    def record_directory(
        self, operation_id: str, ordinal: int, directory: CreatedMoveDirectory
    ) -> None: ...


class MovePublicationPort(Protocol):
    def create_directory(
        self, root: Path, relative_path: str, parent: DestinationInspection
    ) -> FileIdentity: ...
    def validate(self, move: PlannedMove) -> None: ...
    def prepare_copy(self, move: PlannedMove) -> PreparedMoveCopy | None: ...
    def publish(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> None: ...
    def is_published(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> bool: ...
    def finish_source(
        self, move: PlannedMove, copy: PreparedMoveCopy | None = None
    ) -> StagedMoveSource | None: ...


class MoveIndexPort(Protocol):
    def validate(self, move: PlannedMove) -> None: ...

    def apply(
        self,
        move: PlannedMove,
        now: datetime,
        directories: tuple[CreatedMoveDirectory, ...] = (),
    ) -> tuple[str, ...]: ...


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
                    self.index.validate(move)
                    self.uow.rollback()
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
            copy = current.copies[ordinal]
            self.uow.rollback()
            if stage in {"COMPLETED", "FAILED", "CANCELLED"}:
                continue
            if stage == "RECOVERY_REQUIRED":
                return
            # Earlier targets may have created a shared parent. Accept only
            # directories whose identities were journalled by this operation.
            known_directories = {
                directory.relative_path: directory
                for index, directories in enumerate(current.created_directories)
                if plan.moves[index].destination.library_id
                == move.destination.library_id
                for directory in directories
            }
            destination = move.destination_inspection
            missing = list(destination.missing_directories)
            while missing and missing[0] in known_directories:
                shared = known_directories[missing.pop(0)]
                destination = DestinationInspection(
                    tuple(missing),
                    shared.identity.device,
                    shared.identity.inode,
                    shared.relative_path,
                )
            move = replace(move, destination_inspection=destination)
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
                    self.index.validate(move)
                    self.uow.rollback()
                    self.files.validate(move)
                    self.store.checkpoint(
                        operation_id, ordinal, "PREPARING", self.clock_ms()
                    )
                    self.uow.commit()
                    stage = "PREPARING"
                if stage == "PREPARING":
                    created = list(current.created_directories[ordinal])
                    destination = move.destination_inspection
                    for relative in move.destination_inspection.missing_directories:
                        saved = next(
                            (
                                item
                                for item in created
                                if item.relative_path == relative
                            ),
                            None,
                        )
                        if saved is None:
                            require_plan_access(plan, self.authorize(plan.actor))
                            self.uow.rollback()
                            identity = self.files.create_directory(
                                move.destination.root, relative, destination
                            )
                            saved = CreatedMoveDirectory(relative, identity)
                            self.store.record_directory(operation_id, ordinal, saved)
                            self.uow.commit()
                            created.append(saved)
                        destination = DestinationInspection(
                            (), saved.identity.device, saved.identity.inode, relative
                        )
                    if created:
                        move = replace(move, destination_inspection=destination)
                    if move.cross_device and copy is None:
                        require_plan_access(plan, self.authorize(plan.actor))
                        self.uow.rollback()
                        publication_uncertain = True
                        copy = self.files.prepare_copy(move)
                        if copy is None:
                            raise FileMoveError("COPY_NOT_PREPARED")
                        self.store.record_copy(operation_id, ordinal, copy)
                        self.uow.commit()
                    # Reopening an uncertain rename observes only the frozen source
                    # and target. A published item receives minimal index repair,
                    # even if its token has since been revoked.
                    published = self.files.is_published(move, copy)
                    publication_uncertain = published or copy is not None
                    if not published:
                        require_plan_access(plan, self.authorize(plan.actor))
                        self.index.validate(move)
                        cancelled = self.store.execution(operation_id).cancelled
                        self.uow.rollback()
                        if cancelled:
                            if copy is not None:
                                raise FileMoveError("CANCELLED_STAGED_COPY_RETAINED")
                            self.store.checkpoint(
                                operation_id, ordinal, "CANCELLED", self.clock_ms()
                            )
                            self.uow.commit()
                            continue
                        publication_uncertain = True
                        self.files.publish(move, copy)
                    self.store.checkpoint(
                        operation_id, ordinal, "FILES_PUBLISHED", self.clock_ms()
                    )
                    self.uow.commit()
                    stage = "FILES_PUBLISHED"
                if stage == "FILES_PUBLISHED":
                    if not self.files.is_published(move, copy):
                        raise FileMoveError("PUBLISHED_FILE_MISSING")
                    node_ids = self.index.apply(
                        move,
                        self.clock(),
                        self.store.execution(operation_id).created_directories[ordinal],
                    )
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
                self.uow.rollback()
                backup = self.files.finish_source(move, copy)
                if backup is not None:
                    self.store.record_source_backup(
                        operation_id, ordinal, backup, self.clock_ms()
                    )
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
