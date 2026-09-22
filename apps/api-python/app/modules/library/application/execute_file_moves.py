"""Advance durable file moves through publication and index reconciliation."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.contracts.diagnostics import FailureDiagnostics
from app.contracts.source_relocation import SourceRelocation
from app.modules.library.application.file_move_operations import require_move_access
from app.modules.library.application.file_move_plans import (
    CreatedMoveDirectory,
    DestinationInspection,
    FileMovePlan,
    MoveActor,
    PlannedMove,
)
from app.modules.library.domain.file_moves import FileIdentity, FileMoveError


@dataclass(frozen=True)
class MoveExecution:
    plan: FileMovePlan
    stages: tuple[str, ...]
    cancelled: bool
    created_directories: tuple[tuple[CreatedMoveDirectory, ...], ...]


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
    def record_directory(
        self, operation_id: str, ordinal: int, directory: CreatedMoveDirectory
    ) -> None: ...


class MovePublicationPort(Protocol):
    def create_directory(
        self, root: Path, relative_path: str, parent: DestinationInspection
    ) -> FileIdentity: ...
    def validate(self, move: PlannedMove) -> None: ...
    def publish(self, move: PlannedMove) -> None: ...
    def is_published(self, move: PlannedMove) -> bool: ...


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
    diagnostics: FailureDiagnostics

    def execute(self, operation_id: str) -> None:
        execution = self.store.execution(operation_id)
        self.uow.rollback()  # Read snapshot released before filesystem validation.
        plan = execution.plan
        for ordinal, move in enumerate(plan.moves):
            current = self.store.execution(operation_id)
            stage = current.stages[ordinal]
            self.uow.rollback()
            if stage in {"COMPLETED", "FAILED", "CANCELLED"}:
                continue
            if stage == "RECOVERY_REQUIRED":
                continue
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
            companions_published = any(
                previous.companion_owner == (move.companion_owner or move.source)
                and current.stages[index]
                in {"COMPLETED", "INDEX_UPDATED", "FILES_PUBLISHED"}
                for index, previous in enumerate(plan.moves)
            )
            publication_uncertain = stage != "QUEUED" or companions_published
            step = "validate_target"
            try:
                if plan.execution_version != 2:
                    raise FileMoveError("MOVE_PLAN_REQUIRES_REFRESH")
                if stage == "PREPARING":
                    raise FileMoveError("FILE_OPERATION_INTERRUPTED")
                if stage == "QUEUED":
                    if current.cancelled:
                        if companions_published:
                            raise FileMoveError("CANCELLED_COMPANIONS_RETAINED")
                        step = "checkpoint"
                        self.store.checkpoint(
                            operation_id, ordinal, "CANCELLED", self.clock_ms()
                        )
                        step = "commit"
                        self.uow.commit()
                        continue
                    step = "authorize_target"
                    require_move_access(plan.actor, move, self.authorize(plan.actor))
                    self.uow.rollback()
                    step = "validate_index"
                    self.index.validate(move)
                    self.uow.rollback()
                    step = "validate_files"
                    self.files.validate(move)
                    step = "checkpoint"
                    self.store.checkpoint(
                        operation_id, ordinal, "PREPARING", self.clock_ms()
                    )
                    step = "commit"
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
                            require_move_access(
                                plan.actor, move, self.authorize(plan.actor)
                            )
                            self.uow.rollback()
                            step = "create_directory"
                            identity = self.files.create_directory(
                                move.destination.root, relative, destination
                            )
                            saved = CreatedMoveDirectory(relative, identity)
                            self.store.record_directory(operation_id, ordinal, saved)
                            step = "commit"
                            self.uow.commit()
                            created.append(saved)
                        destination = DestinationInspection(
                            (), saved.identity.device, saved.identity.inode, relative
                        )
                    if created:
                        move = replace(move, destination_inspection=destination)
                    step = "inspect_publication"
                    published = self.files.is_published(move)
                    publication_uncertain = published or companions_published
                    if not published:
                        require_move_access(
                            plan.actor, move, self.authorize(plan.actor)
                        )
                        step = "validate_index"
                        self.index.validate(move)
                        cancelled = self.store.execution(operation_id).cancelled
                        self.uow.rollback()
                        if cancelled:
                            if companions_published:
                                raise FileMoveError("CANCELLED_COMPANIONS_RETAINED")
                            step = "checkpoint"
                            self.store.checkpoint(
                                operation_id, ordinal, "CANCELLED", self.clock_ms()
                            )
                            step = "commit"
                            self.uow.commit()
                            continue
                        publication_uncertain = True
                        step = "publish_files"
                        self.files.publish(move)
                    step = "checkpoint"
                    self.store.checkpoint(
                        operation_id, ordinal, "FILES_PUBLISHED", self.clock_ms()
                    )
                    step = "commit"
                    self.uow.commit()
                    stage = "FILES_PUBLISHED"
                if stage == "FILES_PUBLISHED":
                    if not self.files.is_published(move):
                        raise FileMoveError("PUBLISHED_FILE_MISSING")
                    step = "update_index"
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
                    step = "discard_relocated_writebacks"
                    self.discard_writebacks(change)
                    step = "reconcile_imports"
                    self.reconcile_imports(change)
                    step = "checkpoint"
                    self.store.checkpoint(
                        operation_id, ordinal, "INDEX_UPDATED", self.clock_ms()
                    )
                    step = "commit"
                    self.uow.commit()
                self.uow.rollback()
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id, ordinal, "COMPLETED", self.clock_ms()
                )
                step = "commit"
                self.uow.commit()
            except Exception as error:  # noqa: BLE001 - diagnose each target before continuing siblings.
                diagnostic = self.diagnostics.prepare(
                    error,
                    event="file_move.target_failed",
                    context={
                        "operation_id": operation_id,
                        "target_ordinal": ordinal,
                        "library_id": move.source.library_id,
                        "source_node_id": move.source.node_id,
                        "stage": stage,
                        "step": step,
                    },
                )
                try:
                    self.uow.rollback()
                except Exception as rollback_error:
                    secondary = self.diagnostics.prepare(
                        rollback_error,
                        event="file_move.rollback_failed",
                        context={
                            "operation_id": operation_id,
                            "target_ordinal": ordinal,
                            "step": "rollback",
                            "parent_diagnostic_id": diagnostic.diagnostic_id,
                        },
                    )
                    self.diagnostics.persist(secondary)
                    raise
                finally:
                    self.diagnostics.persist(diagnostic)
                known = isinstance(error, FileMoveError)
                state = (
                    "RECOVERY_REQUIRED"
                    if publication_uncertain or not known
                    else "FAILED"
                )
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id,
                    ordinal,
                    state,
                    self.clock_ms(),
                    str(error) if known else "FILE_OPERATION_INTERRUPTED",
                )
                step = "commit"
                self.uow.commit()
        self.store.finish(operation_id, self.clock_ms())
        step = "commit"
        self.uow.commit()
