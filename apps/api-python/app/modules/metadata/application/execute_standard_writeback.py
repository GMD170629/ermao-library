"""Advance one leased standard-file target without holding database locks over I/O."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.contracts.diagnostics import FailureDiagnostics
from app.contracts.file_operation import FileIdentity, FileOperationError
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.application.standard_writeback import (
    PlannedStandardWrite,
    PreparedStandardFile,
    StandardPreparationError,
    StandardWriteFile,
    StandardWritePlan,
)


@dataclass(frozen=True)
class StandardWriteExecution:
    plan: StandardWritePlan
    ordinal: int
    stage: str
    cancelled: bool
    proof: PreparedStandardFile | None


class StandardWriteExecutionStore(Protocol):
    def execution(
        self, operation_id: str, ordinal: int, owner_id: str
    ) -> StandardWriteExecution: ...
    def checkpoint(
        self,
        operation_id: str,
        ordinal: int,
        owner_id: str,
        stage: str,
        now_ms: int,
        *,
        proof: PreparedStandardFile | None = None,
        partial: FileIdentity | None = None,
        error_code: str | None = None,
    ) -> None: ...
    def complete(
        self,
        operation_id: str,
        ordinal: int,
        owner_id: str,
        now_ms: int,
        *,
        cancelled: bool = False,
        failed: str | None = None,
    ) -> None: ...


class StandardPublicationPort(Protocol):
    def prepare(self, target: StandardWriteFile) -> PreparedStandardFile: ...
    def published(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> bool: ...
    def discard_prepared(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> None: ...
    def publish(
        self, target: StandardWriteFile, proof: PreparedStandardFile
    ) -> None: ...


class StandardWriteUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class ExecuteStandardWrite:
    store: StandardWriteExecutionStore
    files: StandardPublicationPort
    authorize: Callable[[StandardWritePlan, PlannedStandardWrite], None]
    record_publication: Callable[
        [str, StandardWritePlan, PlannedStandardWrite, PreparedStandardFile], None
    ]
    uow: StandardWriteUnitOfWork
    clock_ms: Callable[[], int]
    diagnostics: FailureDiagnostics

    def execute(self, operation_id: str, ordinal: int, owner_id: str) -> None:
        entry = self.store.execution(operation_id, ordinal, owner_id)
        self.uow.rollback()
        target = entry.plan.targets[ordinal]
        proof = entry.proof
        uncertain = proof is not None or entry.stage != "QUEUED"
        step = "authorize_target"
        try:
            if proof is None:
                self.authorize(entry.plan, target)
                self.uow.rollback()
                if entry.cancelled:
                    if uncertain:
                        raise StandardMetadataError("CANCELLED_PREPARATION_RETAINED")
                    self.store.complete(
                        operation_id, ordinal, owner_id, self.clock_ms(), cancelled=True
                    )
                    step = "commit"
                    self.uow.commit()
                    return
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id, ordinal, owner_id, "PREPARING", self.clock_ms()
                )
                step = "commit"
                self.uow.commit()
                step = "prepare_file"
                proof = self.files.prepare(target.file)
                uncertain = True
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id,
                    ordinal,
                    owner_id,
                    "PREPARED",
                    self.clock_ms(),
                    proof=proof,
                )
                step = "commit"
                self.uow.commit()
            self.uow.rollback()
            step = "inspect_publication"
            published = self.files.published(target.file, proof)
            if not published:
                self.authorize(entry.plan, target)
                cancelled = self.store.execution(
                    operation_id, ordinal, owner_id
                ).cancelled
                self.uow.rollback()
                if cancelled:
                    step = "discard_prepared"
                    self.files.discard_prepared(target.file, proof)
                    self.store.complete(
                        operation_id, ordinal, owner_id, self.clock_ms(), cancelled=True
                    )
                    step = "commit"
                    self.uow.commit()
                    return
                step = "publish_file"
                self.files.publish(target.file, proof)
            step = "checkpoint"
            self.store.checkpoint(
                operation_id,
                ordinal,
                owner_id,
                "FILES_PUBLISHED",
                self.clock_ms(),
                proof=proof,
            )
            step = "commit"
            self.uow.commit()
            step = "record_publication"
            self.record_publication(operation_id, entry.plan, target, proof)
            self.store.complete(operation_id, ordinal, owner_id, self.clock_ms())
            step = "commit"
            self.uow.commit()
        except Exception as error:  # noqa: BLE001 - uncertain I/O remains journalled with its real cause.
            diagnostic = self.diagnostics.prepare(
                error,
                event="standard_write.target_failed",
                context={
                    "operation_id": operation_id,
                    "target_ordinal": ordinal,
                    "stage": entry.stage,
                    "step": step,
                },
            )
            try:
                self.uow.rollback()
            except Exception as rollback_error:
                secondary = self.diagnostics.prepare(
                    rollback_error,
                    event="standard_write.rollback_failed",
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
            if isinstance(error, StandardPreparationError):
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id,
                    ordinal,
                    owner_id,
                    "RECOVERY_REQUIRED",
                    self.clock_ms(),
                    partial=error.prepared_identity,
                    error_code=str(error),
                )
            elif isinstance(error, (StandardMetadataError, FileOperationError)):
                if uncertain:
                    step = "checkpoint"
                    self.store.checkpoint(
                        operation_id,
                        ordinal,
                        owner_id,
                        "RECOVERY_REQUIRED",
                        self.clock_ms(),
                        error_code=str(error),
                    )
                else:
                    self.store.complete(
                        operation_id,
                        ordinal,
                        owner_id,
                        self.clock_ms(),
                        failed=str(error),
                    )
            else:
                step = "checkpoint"
                self.store.checkpoint(
                    operation_id,
                    ordinal,
                    owner_id,
                    "RECOVERY_REQUIRED",
                    self.clock_ms(),
                    error_code="FILE_WRITE_INTERRUPTED",
                )
            step = "commit"
            self.uow.commit()
