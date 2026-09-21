"""ORM move intent persistence. The calling application owns every transaction."""

from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, aliased

from app.infrastructure.file_recovery_budget import reserved_file_recovery_bytes
from app.models import LibraryBook, LibraryImportTask
from app.models.organize import MetadataWritebackOperation, MetadataWritebackTarget
from app.modules.library.application.execute_file_moves import MoveExecution
from app.modules.library.application.file_move_operations import (
    FileMoveProgress,
    require_plan_access,
)
from app.modules.library.application.file_move_plans import (
    CreatedMoveDirectory,
    FileMovePlan,
    MoveActor,
    PreparedMoveCopy,
    StagedMoveSource,
)
from app.modules.library.application.file_move_recovery_cleanup import ExpiredMoveBackup
from app.modules.library.domain.file_moves import (
    RECOVERY_BYTE_LIMIT,
    RECOVERY_RETENTION_MS,
    FileMoveError,
)
from app.modules.library.infrastructure.file_move_schema import (
    LibraryFileMoveOperation,
    LibraryFileMovePlan,
    LibraryFileMoveTarget,
)
from app.modules.library.infrastructure.operations import (
    prepare_operation_write,
    write_prepared_operation,
)

_PLAN = TypeAdapter(FileMovePlan)
_DIRECTORIES = TypeAdapter(tuple[CreatedMoveDirectory, ...])
_COPY = TypeAdapter(PreparedMoveCopy)
_BACKUP = TypeAdapter(StagedMoveSource)
_TERMINAL = frozenset(
    {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "RECOVERY_REQUIRED"}
)


class SqlAlchemyFileMoveOperations:
    def __init__(
        self, db: Session, *, recovery_byte_limit: int = RECOVERY_BYTE_LIMIT
    ) -> None:
        self._db = db
        self._recovery_byte_limit = recovery_byte_limit

    def save_plan(self, plan: FileMovePlan) -> None:
        self._db.add(
            LibraryFileMovePlan(
                id=plan.id,
                grant_id=plan.actor.grant_id,
                user_id=plan.actor.user_id,
                expires_at_ms=plan.expires_at_ms,
                payload=_PLAN.dump_python(plan, mode="json"),
            )
        )
        self._db.flush()

    def load_plan(self, plan_id: str, actor: MoveActor) -> FileMovePlan:
        row = self._db.scalar(
            select(LibraryFileMovePlan)
            .where(
                LibraryFileMovePlan.id == plan_id,
                LibraryFileMovePlan.grant_id == actor.grant_id,
                LibraryFileMovePlan.user_id == actor.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        plan = _PLAN.validate_python(row.payload)
        require_plan_access(plan, actor)
        return plan

    def enqueue(
        self, plan: FileMovePlan, operation_id: str, request_id: str, now_ms: int
    ) -> str:
        existing = self._db.scalar(
            select(LibraryFileMoveOperation.id).where(
                LibraryFileMoveOperation.plan_id == plan.id
            )
        )
        if existing is not None:
            return existing
        if plan.expires_at_ms <= now_ms:
            raise FileMoveError("PLAN_EXPIRED")
        reserved = reserved_file_recovery_bytes(self._db)
        requested = sum(
            move.inventory.byte_count for move in plan.moves if move.cross_device
        )
        if requested and reserved + requested > self._recovery_byte_limit:
            raise FileMoveError("RECOVERY_QUOTA_EXCEEDED")
        self._db.add(
            LibraryFileMoveOperation(
                id=operation_id,
                plan_id=plan.id,
                grant_id=plan.actor.grant_id,
                user_id=plan.actor.user_id,
                request_id=request_id,
                status="QUEUED",
                cancel_requested=False,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
        )
        self._db.flush()
        self._db.add_all(
            [
                LibraryFileMoveTarget(
                    operation_id=operation_id,
                    ordinal=index,
                    source_library_id=move.source.library_id,
                    destination_library_id=move.destination.library_id,
                    byte_count=move.inventory.byte_count,
                    copy_required=move.cross_device,
                    stage="QUEUED",
                    recovery={},
                )
                for index, move in enumerate(plan.moves)
            ]
        )
        self._db.flush()
        return operation_id

    def _owned(self, operation_id: str, actor: MoveActor) -> LibraryFileMoveOperation:
        row = self._db.scalar(
            select(LibraryFileMoveOperation)
            .where(
                LibraryFileMoveOperation.id == operation_id,
                LibraryFileMoveOperation.grant_id == actor.grant_id,
                LibraryFileMoveOperation.user_id == actor.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        self.load_plan(row.plan_id, actor)
        return row

    def progress(self, operation_id: str, actor: MoveActor) -> FileMoveProgress:
        row = self._owned(operation_id, actor)
        targets = tuple(
            self._db.scalars(
                select(LibraryFileMoveTarget)
                .where(
                    LibraryFileMoveTarget.operation_id == operation_id,
                )
                .order_by(LibraryFileMoveTarget.ordinal)
                .execution_options(populate_existing=True)
            )
        )
        return FileMoveProgress(
            row.id,
            row.plan_id,
            row.status,
            row.cancel_requested,
            tuple(target.stage for target in targets),
            tuple(target.error_code for target in targets),
        )

    def cancel(
        self, operation_id: str, actor: MoveActor, now_ms: int
    ) -> FileMoveProgress:
        row = self._owned(operation_id, actor)
        if row.status not in _TERMINAL:
            row.cancel_requested = True
            row.updated_at_ms = now_ms
            if row.status == "QUEUED":
                row.status = "CANCELLED"
                for target in self._db.scalars(
                    select(LibraryFileMoveTarget).where(
                        LibraryFileMoveTarget.operation_id == operation_id
                    )
                ):
                    target.stage = "CANCELLED"
            self._db.flush()
        return self.progress(operation_id, actor)

    def claim_next(self, now_ms: int) -> str | None:
        """SQLite UPDATE serializes this claim with both existing queue claims."""
        # Explicit correlations keep the candidate operation as the scope owner.
        libraries = (
            select(LibraryFileMoveTarget.source_library_id)
            .where(LibraryFileMoveTarget.operation_id == LibraryFileMoveOperation.id)
            .correlate(LibraryFileMoveOperation)
            .union(
                select(LibraryFileMoveTarget.destination_library_id)
                .where(
                    LibraryFileMoveTarget.operation_id == LibraryFileMoveOperation.id
                )
                .correlate(LibraryFileMoveOperation)
            )
        )
        running_import = (
            select(LibraryImportTask.id)
            .where(
                LibraryImportTask.library_id.in_(libraries),
                LibraryImportTask.state == "RUNNING",
            )
            .exists()
        )
        running_writeback = (
            select(MetadataWritebackTarget.id)
            .join(
                MetadataWritebackOperation,
                MetadataWritebackOperation.id == MetadataWritebackTarget.operation_id,
            )
            .join(LibraryBook, LibraryBook.id == MetadataWritebackOperation.book_id)
            .where(
                LibraryBook.library_id.in_(libraries),
                MetadataWritebackTarget.status.in_(("RUNNING", "PREPARED", "REVIEW")),
            )
            .exists()
        )
        other_operation = aliased(LibraryFileMoveOperation)
        other_target = aliased(LibraryFileMoveTarget)
        active_move = (
            select(other_operation.id)
            .join(other_target, other_target.operation_id == other_operation.id)
            .where(
                other_operation.id != LibraryFileMoveOperation.id,
                other_operation.status.in_(
                    (
                        "PREPARING",
                        "FILES_PUBLISHED",
                        "INDEX_UPDATED",
                        "RECOVERY_REQUIRED",
                    )
                ),
                or_(
                    other_target.source_library_id.in_(libraries),
                    other_target.destination_library_id.in_(libraries),
                ),
            )
            .exists()
        )
        candidate = (
            select(LibraryFileMoveOperation.id)
            .where(
                LibraryFileMoveOperation.status == "QUEUED",
                LibraryFileMoveOperation.cancel_requested.is_(False),
                ~running_import,
                ~running_writeback,
                ~active_move,
            )
            .order_by(
                LibraryFileMoveOperation.created_at_ms, LibraryFileMoveOperation.id
            )
            .limit(1)
            .scalar_subquery()
        )
        return self._db.scalar(
            update(LibraryFileMoveOperation)
            .where(
                LibraryFileMoveOperation.id == candidate,
            )
            .values(status="PREPARING", updated_at_ms=now_ms)
            .returning(LibraryFileMoveOperation.id)
        )

    def execution(self, operation_id: str) -> MoveExecution:
        row = self._db.get(
            LibraryFileMoveOperation, operation_id, populate_existing=True
        )
        if row is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        if row.status == "QUEUED":
            raise FileMoveError("OPERATION_NOT_CLAIMED")
        plan_row = self._db.get(LibraryFileMovePlan, row.plan_id)
        if plan_row is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        plan = _PLAN.validate_python(plan_row.payload)
        stages = tuple(
            self._db.scalars(
                select(LibraryFileMoveTarget.stage)
                .where(
                    LibraryFileMoveTarget.operation_id == operation_id,
                )
                .order_by(LibraryFileMoveTarget.ordinal)
            )
        )
        directories = tuple(
            _DIRECTORIES.validate_python(target.recovery.get("directories", []))
            for target in self._db.scalars(
                select(LibraryFileMoveTarget)
                .where(LibraryFileMoveTarget.operation_id == operation_id)
                .order_by(LibraryFileMoveTarget.ordinal)
                .execution_options(populate_existing=True)
            )
        )
        copies = tuple(
            _COPY.validate_python(target.recovery["copy"])
            if "copy" in target.recovery
            else None
            for target in self._db.scalars(
                select(LibraryFileMoveTarget)
                .where(LibraryFileMoveTarget.operation_id == operation_id)
                .order_by(LibraryFileMoveTarget.ordinal)
                .execution_options(populate_existing=True)
            )
        )
        return MoveExecution(plan, stages, row.cancel_requested, directories, copies)

    def checkpoint(
        self,
        operation_id: str,
        ordinal: int,
        stage: str,
        now_ms: int,
        error_code: str | None = None,
    ) -> None:
        if stage == "INDEX_UPDATED":
            execution = self.execution(operation_id)
            move = execution.plan.moves[ordinal]
            prepared = prepare_operation_write(
                user_id=execution.plan.actor.user_id,
                action="MOVE_FILES",
                target_type="sourceNode",
                target_id=move.source.node_id,
                summary="已移动图书文件 / Book files moved",
                payload={
                    "grantId": execution.plan.actor.grant_id,
                    "operationId": operation_id,
                    "sourceLibraryId": move.source.library_id,
                    "sourceRelativePath": move.source.relative_path,
                    "destinationLibraryId": move.destination.library_id,
                    "destinationRelativePath": move.destination.relative_path,
                    "bookIds": move.source.book_ids,
                },
                inverse={},
                now=datetime.fromtimestamp(now_ms / 1000, UTC),
                undoable=False,
            )
            write_prepared_operation(self._db, prepared)
        if stage == "RECOVERY_REQUIRED":
            target = self._db.get(
                LibraryFileMoveTarget, (operation_id, ordinal), populate_existing=True
            )
            if target is None:
                raise FileMoveError("RESOURCE_NOT_FOUND")
            if target.stage != "RECOVERY_REQUIRED":
                target.recovery = {**target.recovery, "resume_stage": target.stage}
                self._db.flush()
        self._db.execute(
            update(LibraryFileMoveTarget)
            .where(
                LibraryFileMoveTarget.operation_id == operation_id,
                LibraryFileMoveTarget.ordinal == ordinal,
            )
            .values(stage=stage, error_code=error_code)
        )
        self._db.execute(
            update(LibraryFileMoveOperation)
            .where(LibraryFileMoveOperation.id == operation_id)
            .values(updated_at_ms=now_ms)
        )

    def finish(self, operation_id: str, now_ms: int) -> None:
        stages = set(self.execution(operation_id).stages)
        if "RECOVERY_REQUIRED" in stages:
            status = "RECOVERY_REQUIRED"
        elif stages == {"COMPLETED"}:
            status = "COMPLETED"
        elif stages == {"CANCELLED"}:
            status = "CANCELLED"
        elif stages == {"FAILED"}:
            status = "FAILED"
        elif stages <= {"COMPLETED", "FAILED", "CANCELLED"}:
            status = "PARTIAL"
        else:
            status = "PREPARING"
        self._db.execute(
            update(LibraryFileMoveOperation)
            .where(LibraryFileMoveOperation.id == operation_id)
            .values(status=status, updated_at_ms=now_ms)
        )

    def next_recovery(self, after: str) -> str | None:
        return self._db.scalar(
            select(LibraryFileMoveOperation.id)
            .where(
                LibraryFileMoveOperation.id > after,
                LibraryFileMoveOperation.status.in_(
                    (
                        "PREPARING",
                        "FILES_PUBLISHED",
                        "INDEX_UPDATED",
                        "RECOVERY_REQUIRED",
                    )
                ),
            )
            .order_by(LibraryFileMoveOperation.id)
            .limit(1)
        )

    def prepare_recovery(self, operation_id: str, now_ms: int) -> None:
        """Worker-start recovery only; no I/O or target expansion occurs here."""
        targets = tuple(
            self._db.scalars(
                select(LibraryFileMoveTarget).where(
                    LibraryFileMoveTarget.operation_id == operation_id,
                    LibraryFileMoveTarget.stage == "RECOVERY_REQUIRED",
                )
            )
        )
        for target in targets:
            resume = target.recovery.get("resume_stage")
            if resume not in {
                "QUEUED",
                "PREPARING",
                "FILES_PUBLISHED",
                "INDEX_UPDATED",
            }:
                raise FileMoveError("RECOVERY_STAGE_UNKNOWN")
            target.stage = str(resume)
            target.error_code = None
        self._db.execute(
            update(LibraryFileMoveOperation)
            .where(LibraryFileMoveOperation.id == operation_id)
            .values(status="PREPARING", updated_at_ms=now_ms)
        )
        self._db.flush()

    def record_directory(
        self, operation_id: str, ordinal: int, directory: CreatedMoveDirectory
    ) -> None:
        target = self._db.get(
            LibraryFileMoveTarget, (operation_id, ordinal), populate_existing=True
        )
        if target is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        existing = _DIRECTORIES.validate_python(target.recovery.get("directories", []))
        target.recovery = {
            **target.recovery,
            "directories": _DIRECTORIES.dump_python(
                (*existing, directory), mode="json"
            ),
        }
        self._db.flush()

    def record_copy(
        self, operation_id: str, ordinal: int, copy: PreparedMoveCopy
    ) -> None:
        target = self._db.get(
            LibraryFileMoveTarget, (operation_id, ordinal), populate_existing=True
        )
        if target is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        target.recovery = {
            **target.recovery,
            "copy": _COPY.dump_python(copy, mode="json"),
        }
        self._db.flush()

    def record_source_backup(
        self, operation_id: str, ordinal: int, backup: StagedMoveSource, now_ms: int
    ) -> None:
        target = self._db.get(
            LibraryFileMoveTarget, (operation_id, ordinal), populate_existing=True
        )
        if target is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        target.recovery = {
            **target.recovery,
            "source_backup": _BACKUP.dump_python(backup, mode="json"),
            "source_backup_expires_at": now_ms + RECOVERY_RETENTION_MS,
        }
        self._db.flush()

    def expired_backups(self, now_ms: int, limit: int) -> tuple[ExpiredMoveBackup, ...]:
        targets = tuple(
            self._db.scalars(
                select(LibraryFileMoveTarget)
                .join(
                    LibraryFileMoveOperation,
                    LibraryFileMoveOperation.id == LibraryFileMoveTarget.operation_id,
                )
                .where(
                    LibraryFileMoveOperation.status.in_(("COMPLETED", "PARTIAL")),
                    LibraryFileMoveTarget.stage == "COMPLETED",
                    LibraryFileMoveTarget.recovery[
                        "source_backup_expires_at"
                    ].as_integer()
                    <= now_ms,
                    LibraryFileMoveTarget.recovery["source_backup_cleared_at"]
                    .as_integer()
                    .is_(None),
                    or_(
                        LibraryFileMoveTarget.recovery["backup_retry_at"]
                        .as_integer()
                        .is_(None),
                        LibraryFileMoveTarget.recovery["backup_retry_at"].as_integer()
                        <= now_ms,
                    ),
                )
                .order_by(
                    LibraryFileMoveOperation.updated_at_ms,
                    LibraryFileMoveTarget.ordinal,
                )
                .limit(min(max(limit, 1), 5))
                .execution_options(populate_existing=True)
            )
        )
        results: list[ExpiredMoveBackup] = []
        for target in targets:
            execution = self.execution(target.operation_id)
            results.append(
                ExpiredMoveBackup(
                    target.operation_id,
                    target.ordinal,
                    execution.plan.moves[target.ordinal],
                    _COPY.validate_python(target.recovery["copy"]),
                    _BACKUP.validate_python(target.recovery["source_backup"]),
                )
            )
        return tuple(results)

    def clear_backup(self, backup: ExpiredMoveBackup, now_ms: int) -> None:
        target = self._db.get(
            LibraryFileMoveTarget,
            (backup.operation_id, backup.ordinal),
            populate_existing=True,
        )
        if target is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        target.recovery = {
            **target.recovery,
            "source_backup_cleared_at": now_ms,
            "backup_cleanup_error": None,
        }
        self._db.flush()

    def retain_backup(
        self, backup: ExpiredMoveBackup, error_code: str, now_ms: int
    ) -> None:
        target = self._db.get(
            LibraryFileMoveTarget,
            (backup.operation_id, backup.ordinal),
            populate_existing=True,
        )
        if target is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        target.recovery = {
            **target.recovery,
            "backup_cleanup_error": error_code,
            "backup_retry_at": now_ms + 24 * 60 * 60_000,
        }
        self._db.flush()
