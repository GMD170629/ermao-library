"""MCP authorization for frozen permanent file deletions."""

from dataclasses import dataclass, replace

from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.library.public import DeletePlan, FileDeletions, FileMoveError


def deletion_result(plan: DeletePlan) -> dict[str, object]:
    stages = [target.stage for target in plan.targets]
    status = (
        "COMPLETED"
        if all(stage == "COMPLETED" for stage in stages)
        else "PARTIAL"
        if "COMPLETED" in stages
        else "FAILED"
        if all(stage in {"FAILED", "CANCELLED"} for stage in stages)
        else "RECOVERY_REQUIRED"
        if any(target.error for target in plan.targets)
        else "RUNNING"
        if plan.executing
        else "PLANNED"
    )
    return {
        "plan_id": plan.id,
        "operation_id": plan.id if plan.executing else None,
        "kind": "file_delete",
        "status": status,
        "expires_at_ms": plan.expires_at_ms,
        "cancel_requested": plan.cancelled,
        "targets": [
            {
                "library_id": target.source.library_id,
                "relative_path": target.source.relative_path,
                "stage": target.stage,
                "error_code": target.error,
                "files": [entry.relative_path for entry in target.inventory.entries],
                "bytes": target.inventory.byte_count,
            }
            for target in plan.targets
        ],
    }


@dataclass(frozen=True)
class RecheckDeleteAccess:
    authorization: RecheckMutationAccess
    access: EffectiveAccess

    def library_ids(self) -> frozenset[str]:
        try:
            return self.authorization.require(
                self.access, Scope.FILES_MODIFY
            ).permissions.library_ids
        except AutomationAccessError as error:
            raise FileMoveError("AUTHORIZATION_REVOKED") from error


@dataclass(frozen=True)
class AutomationDeletions:
    files: FileDeletions
    authorization: RecheckMutationAccess

    def plan(
        self, access: EffectiveAccess, node_ids: tuple[str, ...]
    ) -> dict[str, object]:
        current = self.authorization.require(access, Scope.FILES_MODIFY)
        return deletion_result(
            self.files.plan(
                current.user_id,
                current.grant_id,
                current.permissions.library_ids,
                node_ids,
            )
        )

    def _authorize(self, access: EffectiveAccess) -> frozenset[str]:
        return RecheckDeleteAccess(self.authorization, access).library_ids()

    def execute(self, access: EffectiveAccess, plan_id: str) -> dict[str, object]:
        self._authorize(access)
        return deletion_result(
            self.files.execute(
                plan_id,
                access.user_id,
                access.grant_id,
                RecheckDeleteAccess(self.authorization, access),
            )
        )

    def progress(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        libraries = self._authorize(access)
        plan = self.files.store.load(operation_id, access.user_id, access.grant_id)
        if any(target.source.library_id not in libraries for target in plan.targets):
            raise FileMoveError("RESOURCE_NOT_FOUND")
        return deletion_result(self.files.observed(plan))

    def cancel(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        self.progress(access, operation_id)
        plan = replace(
            self.files.store.load(operation_id, access.user_id, access.grant_id),
            cancelled=True,
        )
        self.files.store.save(plan)
        self.files.uow.commit()
        return deletion_result(self.files.observed(plan))
