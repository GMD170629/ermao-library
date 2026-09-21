"""ORM move intent persistence. The calling application owns every transaction."""

from pydantic import TypeAdapter
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, aliased

from app.models import LibraryBook, LibraryImportTask
from app.models.organize import MetadataWritebackOperation, MetadataWritebackTarget
from app.modules.library.application.file_move_operations import (
    FileMoveProgress,
    require_plan_access,
)
from app.modules.library.application.file_move_plans import FileMovePlan, MoveActor
from app.modules.library.domain.file_moves import FileMoveError
from app.modules.library.infrastructure.file_move_schema import (
    LibraryFileMoveOperation,
    LibraryFileMovePlan,
    LibraryFileMoveTarget,
)

_PLAN = TypeAdapter(FileMovePlan)
_TERMINAL = frozenset(
    {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "RECOVERY_REQUIRED"}
)


class SqlAlchemyFileMoveOperations:
    def __init__(self, db: Session) -> None:
        self._db = db

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
                MetadataWritebackTarget.status.in_(("RUNNING", "PREPARED")),
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
