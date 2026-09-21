"""Persist immutable plans and enqueue them through the existing metadata queue."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.contracts.file_operation import FileIdentity
from app.infrastructure.file_recovery_budget import reserved_file_recovery_bytes
from app.models.organize import MetadataWritebackOperation, MetadataWritebackTarget
from app.modules.metadata.application.execute_standard_writeback import (
    StandardWriteExecution,
)
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.application.standard_writeback import (
    STANDARD_PREPARATION_OVERHEAD,
    PreparedStandardFile,
    StandardWritePlan,
    StandardWriteStatus,
)
from app.modules.metadata.infrastructure.standard_writeback_schema import (
    MetadataStandardWriteOperation,
    MetadataStandardWritePlan,
    MetadataStandardWriteTarget,
)
from app.modules.metadata.infrastructure.writeback_queue import (
    complete_target,
    reserve_direct_writeback_targets,
)

_PLAN = TypeAdapter(StandardWritePlan)
_PROOF = TypeAdapter(PreparedStandardFile)
_IDENTITY = TypeAdapter(FileIdentity)


class SqlAlchemyStandardWritePlans:
    def __init__(
        self,
        db: Session,
        *,
        queue_capacity: int,
        recovery_byte_limit: int = 100 * 1024**3,
    ) -> None:
        self._db = db
        self._capacity = queue_capacity
        self._recovery_limit = recovery_byte_limit

    def save(self, plan: StandardWritePlan) -> None:
        self._db.add(
            MetadataStandardWritePlan(
                id=plan.id,
                grant_id=plan.grant_id,
                user_id=plan.user_id,
                expires_at_ms=plan.expires_at_ms,
                payload=_PLAN.dump_python(plan, mode="json"),
            )
        )
        self._db.flush()

    def load(self, plan_id: str, grant_id: str, user_id: str) -> StandardWritePlan:
        row = self._db.scalar(
            select(MetadataStandardWritePlan)
            .where(
                MetadataStandardWritePlan.id == plan_id,
                MetadataStandardWritePlan.grant_id == grant_id,
                MetadataStandardWritePlan.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise StandardMetadataError("RESOURCE_NOT_FOUND")
        return _PLAN.validate_python(row.payload)

    def enqueue(
        self, plan: StandardWritePlan, operation_id: str, request_id: str, now_ms: int
    ) -> str:
        previous = self._db.scalar(
            select(MetadataStandardWriteOperation.id).where(
                MetadataStandardWriteOperation.plan_id == plan.id
            )
        )
        if previous is not None:
            return previous
        if now_ms >= plan.expires_at_ms:
            raise StandardMetadataError("PLAN_EXPIRED")
        if not 1 <= len(plan.targets) <= 20:
            raise StandardMetadataError("INVALID_TARGETS")
        sizes = [
            (target.file.original.size if target.file.original else 0)
            + STANDARD_PREPARATION_OVERHEAD
            for target in plan.targets
        ]
        if reserved_file_recovery_bytes(self._db) + sum(sizes) > self._recovery_limit:
            raise StandardMetadataError("RECOVERY_QUOTA_EXCEEDED")
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        if not reserve_direct_writeback_targets(
            self._db, len(plan.targets), self._capacity, now
        ):
            raise StandardMetadataError("WRITEBACK_QUEUE_FULL")
        self._db.add(
            MetadataStandardWriteOperation(
                id=operation_id,
                plan_id=plan.id,
                grant_id=plan.grant_id,
                user_id=plan.user_id,
                request_id=request_id,
                cancel_requested=False,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
        )
        self._db.flush()
        operations = []
        queue_targets = []
        results = []
        for ordinal, target in enumerate(plan.targets):
            queue_id = hashlib.sha256(f"{operation_id}:{ordinal}".encode()).hexdigest()
            operations.append(
                {
                    "id": queue_id,
                    "book_id": target.book_id,
                    "source_node_id": target.source_node_id,
                    "resource_id": target.resource_id,
                    "asset_id": target.asset_id,
                    "source": "MCP",
                    "status": "PENDING",
                    "total_targets": 1,
                    "completed_targets": 0,
                    "warning_targets": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            queue_targets.append(
                {
                    "id": queue_id,
                    "operation_id": queue_id,
                    "asset_id": target.asset_id,
                    "target_key": queue_id,
                    "source_path": str(target.file.root / target.file.relative_path),
                    "format": target.file.format,
                    "payload_json": json.dumps(
                        {"standard_operation_id": operation_id, "ordinal": ordinal}
                    ),
                    "status": "PENDING",
                    "attempts": 0,
                    "written_fields_json": "[]",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            results.append(
                {
                    "operation_id": operation_id,
                    "ordinal": ordinal,
                    "library_id": target.file.library_id,
                    "queue_target_id": queue_id,
                    "stage": "QUEUED",
                    "recovery": {},
                    "error_code": None,
                    "reserved_bytes": sizes[ordinal],
                    "recovery_released": False,
                }
            )
        self._db.execute(
            insert(MetadataWritebackOperation).execution_options(render_nulls=True),
            operations,
        )
        self._db.execute(
            insert(MetadataWritebackTarget).execution_options(render_nulls=True),
            queue_targets,
        )
        self._db.execute(
            insert(MetadataStandardWriteTarget).execution_options(render_nulls=True),
            results,
        )
        return operation_id

    def _owned(
        self, operation_id: str, ordinal: int, owner_id: str
    ) -> MetadataStandardWriteTarget:
        target = self._db.scalar(
            select(MetadataStandardWriteTarget)
            .join(
                MetadataWritebackTarget,
                MetadataWritebackTarget.id
                == MetadataStandardWriteTarget.queue_target_id,
            )
            .where(
                MetadataStandardWriteTarget.operation_id == operation_id,
                MetadataStandardWriteTarget.ordinal == ordinal,
                MetadataWritebackTarget.lease_owner_id == owner_id,
            )
            .execution_options(populate_existing=True)
        )
        if target is None:
            raise StandardMetadataError("WRITEBACK_LEASE_LOST")
        return target

    def execution(
        self, operation_id: str, ordinal: int, owner_id: str
    ) -> StandardWriteExecution:
        target = self._owned(operation_id, ordinal, owner_id)
        operation = self._db.get(
            MetadataStandardWriteOperation, operation_id, populate_existing=True
        )
        if operation is None:
            raise StandardMetadataError("RESOURCE_NOT_FOUND")
        plan = self.load(operation.plan_id, operation.grant_id, operation.user_id)
        if not 0 <= ordinal < len(plan.targets):
            raise StandardMetadataError("INVALID_TARGET")
        proof = (
            _PROOF.validate_python(target.recovery["proof"])
            if target.recovery.get("proof") is not None
            else None
        )
        return StandardWriteExecution(
            plan, ordinal, target.stage, operation.cancel_requested, proof
        )

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
    ) -> None:
        target = self._owned(operation_id, ordinal, owner_id)
        recovery = dict(target.recovery)
        if proof is not None:
            recovery["proof"] = _PROOF.dump_python(proof, mode="json")
        if partial is not None:
            recovery["partial"] = _IDENTITY.dump_python(partial, mode="json")
        if stage == "RECOVERY_REQUIRED":
            recovery["resume_stage"] = target.stage
        target.stage = stage
        target.recovery = recovery
        target.error_code = error_code
        queue = self._db.get(
            MetadataWritebackTarget, target.queue_target_id, populate_existing=True
        )
        if queue is None:
            raise StandardMetadataError("WRITEBACK_LEASE_LOST")
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        queue.status = (
            "REVIEW"
            if stage == "RECOVERY_REQUIRED"
            else "PREPARED"
            if proof is not None
            else "RUNNING"
        )
        queue.updated_at = now
        queue.lease_expires_at = now + timedelta(seconds=60)
        self._db.flush()

    def complete(
        self,
        operation_id: str,
        ordinal: int,
        owner_id: str,
        now_ms: int,
        *,
        cancelled: bool = False,
        failed: str | None = None,
    ) -> None:
        target = self._owned(operation_id, ordinal, owner_id)
        execution = self.execution(operation_id, ordinal, owner_id)
        original = execution.plan.targets[ordinal].file.original
        target.stage = "FAILED" if failed else "CANCELLED" if cancelled else "COMPLETED"
        target.error_code = failed
        target.recovery_released = bool(failed or cancelled or original is None)
        if not target.recovery_released:
            target.recovery = {
                **target.recovery,
                "source_backup_expires_at": now_ms + 2 * 24 * 60 * 60_000,
            }
        self._db.flush()
        if not complete_target(
            self._db,
            target.queue_target_id,
            owner_id=owner_id,
            written_fields=(),
            size_bytes=None,
            mtime_ms=None,
            now=datetime.fromtimestamp(now_ms / 1000, UTC),
        ):
            raise StandardMetadataError("WRITEBACK_LEASE_LOST")

    def expired_backups(
        self, now_ms: int
    ) -> tuple[tuple[str, int, StandardWritePlan, PreparedStandardFile], ...]:
        rows = self._db.scalars(
            select(MetadataStandardWriteTarget)
            .where(
                MetadataStandardWriteTarget.stage == "COMPLETED",
                MetadataStandardWriteTarget.recovery_released.is_(False),
                MetadataStandardWriteTarget.recovery[
                    "source_backup_expires_at"
                ].as_integer()
                <= now_ms,
            )
            .order_by(
                MetadataStandardWriteTarget.operation_id,
                MetadataStandardWriteTarget.ordinal,
            )
            .limit(5)
        )
        results = []
        for row in rows:
            operation = self._db.get(MetadataStandardWriteOperation, row.operation_id)
            if operation is None:
                raise StandardMetadataError("RESOURCE_NOT_FOUND")
            plan = self.load(operation.plan_id, operation.grant_id, operation.user_id)
            results.append(
                (
                    row.operation_id,
                    row.ordinal,
                    plan,
                    _PROOF.validate_python(row.recovery["proof"]),
                )
            )
        return tuple(results)

    def backup_cleanup_result(
        self, operation_id: str, ordinal: int, now_ms: int, *, failed: bool
    ) -> None:
        row = self._db.get(MetadataStandardWriteTarget, (operation_id, ordinal))
        if row is None or row.stage != "COMPLETED":
            raise StandardMetadataError("RESOURCE_NOT_FOUND")
        row.recovery_released = not failed
        row.recovery = {
            **row.recovery,
            **(
                {
                    "source_backup_expires_at": now_ms + 24 * 60 * 60_000,
                    "cleanup_error": "BACKUP_RETAINED",
                }
                if failed
                else {"source_backup_cleared_at": now_ms, "cleanup_error": None}
            ),
        }
        self._db.flush()

    def progress(
        self, operation_id: str, grant_id: str, user_id: str
    ) -> StandardWriteStatus:
        operation = self._db.scalar(
            select(MetadataStandardWriteOperation)
            .where(
                MetadataStandardWriteOperation.id == operation_id,
                MetadataStandardWriteOperation.grant_id == grant_id,
                MetadataStandardWriteOperation.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        if operation is None:
            raise StandardMetadataError("RESOURCE_NOT_FOUND")
        plan = self.load(operation.plan_id, grant_id, user_id)
        targets = tuple(
            self._db.scalars(
                select(MetadataStandardWriteTarget)
                .where(MetadataStandardWriteTarget.operation_id == operation_id)
                .order_by(MetadataStandardWriteTarget.ordinal)
                .execution_options(populate_existing=True)
            )
        )
        return StandardWriteStatus(
            operation_id,
            plan,
            tuple(target.stage for target in targets),
            tuple(target.error_code for target in targets),
            operation.cancel_requested,
        )

    def cancel(
        self, operation_id: str, grant_id: str, user_id: str, now_ms: int
    ) -> StandardWriteStatus:
        self.progress(operation_id, grant_id, user_id)
        self._db.execute(
            update(MetadataStandardWriteOperation)
            .where(
                MetadataStandardWriteOperation.id == operation_id,
                MetadataStandardWriteOperation.grant_id == grant_id,
                MetadataStandardWriteOperation.user_id == user_id,
            )
            .values(cancel_requested=True, updated_at_ms=now_ms)
        )
        return self.progress(operation_id, grant_id, user_id)

    def recover_verified_targets(self, now_ms: int) -> int:
        """Once at startup, let the existing lease-aware queue retry known proofs."""
        rows = self._db.scalars(
            select(MetadataStandardWriteTarget).where(
                MetadataStandardWriteTarget.stage == "RECOVERY_REQUIRED",
                MetadataStandardWriteTarget.recovery["proof"].is_not(None),
            )
        )
        count = 0
        for row in rows:
            if row.recovery.get("proof") is None:
                continue
            queue = self._db.get(MetadataWritebackTarget, row.queue_target_id)
            if queue is None or queue.status != "REVIEW":
                continue
            _PROOF.validate_python(row.recovery["proof"])
            queue.status = "PREPARED"
            queue.updated_at = datetime.fromtimestamp(now_ms / 1000, UTC)
            count += 1
        self._db.flush()
        return count
