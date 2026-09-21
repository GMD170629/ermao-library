"""Save immutable standard-file previews and submit idempotent queued writes."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.application.grants import GrantUnitOfWork
from app.modules.automation.application.receipts import (
    ReceiptStore,
    request_fingerprint,
)
from app.modules.automation.application.writeback_plans import (
    BuildStandardWritePlan,
    StandardWriteSelection,
)
from app.modules.automation.domain.access import EffectiveAccess, Scope, WritebackTarget
from app.modules.metadata.public import (
    StandardWritePlan,
    StandardWritePlanStore,
    StandardWriteStatus,
)


def require_writeback_plan(access: EffectiveAccess, plan: StandardWritePlan) -> None:
    access.require(Scope.METADATA_WRITEBACK)
    for target in plan.targets:
        access.require_writeback(
            WritebackTarget.SIDECAR
            if target.file.format in {"OPF", "ComicInfo"}
            else WritebackTarget.EMBEDDED,
            target.file.library_id,
        )


def writeback_plan_result(plan: StandardWritePlan) -> dict[str, object]:
    return {
        "plan_id": plan.id,
        "expires_at": plan.expires_at_ms,
        "targets": [
            {
                "node_id": target.source_node_id,
                "library_id": target.file.library_id,
                "relative_path": target.file.relative_path,
                "format": target.file.format,
                "fields": sorted(target.file.fields),
                "creates_file": target.file.original is None,
                "before": {
                    name: getattr(target.before, name)
                    for name in sorted(target.file.fields)
                },
                "after": {
                    name: getattr(target.file.values, name)
                    for name in sorted(target.file.fields)
                },
            }
            for target in plan.targets
        ],
    }


def writeback_progress_result(status: StandardWriteStatus) -> dict[str, object]:
    return {
        "operation_id": status.operation_id,
        "kind": "metadata_writeback",
        "plan_id": status.plan.id,
        "cancel_requested": status.cancel_requested,
        "targets": [
            {
                "node_id": target.source_node_id,
                "relative_path": target.file.relative_path,
                "format": target.file.format,
                "fields": sorted(target.file.fields),
                "stage": stage,
                "error_code": error,
            }
            for target, stage, error in zip(
                status.plan.targets, status.stages, status.errors, strict=True
            )
        ],
    }


@dataclass(frozen=True)
class AutomationWritebacks:
    planner: BuildStandardWritePlan
    store: StandardWritePlanStore
    receipts: ReceiptStore
    authorization: RecheckMutationAccess
    uow: GrantUnitOfWork
    clock_ms: Callable[[], int]
    new_id: Callable[[], str]

    def plan(
        self, access: EffectiveAccess, requests: tuple[StandardWriteSelection, ...]
    ) -> dict[str, object]:
        plan = self.planner.execute(access, requests)
        try:
            current = self.authorization.require(
                access, Scope.FILES_READ, Scope.METADATA_WRITEBACK
            )
            require_writeback_plan(current, plan)
            self.store.save(plan)
            self.uow.commit()
            return writeback_plan_result(plan)
        except Exception:
            self.uow.rollback()
            raise

    def execute(
        self, access: EffectiveAccess, plan_id: str, request_id: str
    ) -> dict[str, object]:
        access.require(Scope.METADATA_WRITEBACK)
        tool = "execute_metadata_writeback"
        fingerprint = request_fingerprint(tool, {"plan_id": plan_id}, request_id)
        try:
            previous = self.receipts.claim(
                access.grant_id, request_id, tool, fingerprint, self.clock_ms()
            )
            current = self.authorization.require(access, Scope.METADATA_WRITEBACK)
            plan = self.store.load(plan_id, current.grant_id, current.user_id)
            require_writeback_plan(current, plan)
            if previous is not None:
                self.uow.rollback()
                return previous
            operation_id = self.store.enqueue(
                plan, self.new_id(), request_id, self.clock_ms()
            )
            result: dict[str, object] = {
                "operation_id": operation_id,
                "plan_id": plan_id,
            }
            self.receipts.complete(access.grant_id, request_id, result)
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise

    def progress(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        access.require(Scope.METADATA_WRITEBACK)
        status = self.store.progress(operation_id, access.grant_id, access.user_id)
        require_writeback_plan(access, status.plan)
        return writeback_progress_result(status)

    def cancel(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        access.require(Scope.METADATA_WRITEBACK)
        try:
            status = self.store.cancel(
                operation_id, access.grant_id, access.user_id, self.clock_ms()
            )
            current = self.authorization.require(access, Scope.METADATA_WRITEBACK)
            require_writeback_plan(current, status.plan)
            self.uow.commit()
            return writeback_progress_result(status)
        except Exception:
            self.uow.rollback()
            raise
