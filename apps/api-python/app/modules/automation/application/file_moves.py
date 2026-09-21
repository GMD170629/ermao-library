"""Authorize immutable plans and idempotent file-task submission."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.automation.application.execution import RecheckMutationAccess
from app.modules.automation.application.grants import GrantUnitOfWork
from app.modules.automation.application.receipts import (
    ReceiptStore,
    request_fingerprint,
)
from app.modules.automation.domain.access import EffectiveAccess, Scope
from app.modules.library.public import (
    FileMoveOperationPort,
    MoveActor,
    MoveRequest,
    PrepareFileMovePlan,
    move_plan_result,
    move_progress_result,
    require_plan_access,
)


def move_actor(access: EffectiveAccess) -> MoveActor:
    return MoveActor(
        access.user_id,
        access.grant_id,
        access.permissions.library_ids,
        access.permissions.allow_cross_library,
    )


@dataclass(frozen=True)
class AutomationFileMoves:
    planner: PrepareFileMovePlan
    store: FileMoveOperationPort
    receipts: ReceiptStore
    authorization: RecheckMutationAccess
    uow: GrantUnitOfWork
    clock_ms: Callable[[], int]
    new_id: Callable[[], str]

    def plan(
        self, access: EffectiveAccess, requests: tuple[MoveRequest, ...]
    ) -> dict[str, object]:
        access.require(Scope.FILES_READ, Scope.FILES_MOVE)
        plan = self.planner.execute(move_actor(access), requests)
        try:
            current = self.authorization.require(
                access, Scope.FILES_READ, Scope.FILES_MOVE
            )
            require_plan_access(plan, move_actor(current))
            self.store.save_plan(plan)
            self.uow.commit()
            return move_plan_result(plan)
        except Exception:
            self.uow.rollback()
            raise

    def execute(
        self, access: EffectiveAccess, plan_id: str, request_id: str
    ) -> dict[str, object]:
        access.require(Scope.FILES_MOVE)
        tool = "execute_file_operations"
        fingerprint = request_fingerprint(tool, {"plan_id": plan_id}, request_id)
        try:
            previous = self.receipts.claim(
                access.grant_id, request_id, tool, fingerprint, self.clock_ms()
            )
            current = self.authorization.require(access, Scope.FILES_MOVE)
            actor = move_actor(current)
            plan = self.store.load_plan(plan_id, actor)
            if previous is not None:
                self.store.progress(str(previous["operation_id"]), actor)
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
        access.require(Scope.FILES_MOVE)
        return move_progress_result(
            self.store.progress(operation_id, move_actor(access))
        )

    def cancel(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        access.require(Scope.FILES_MOVE)
        try:
            # The conditional cancellation update obtains the same transaction
            # reservation as other commands; revoke races are rechecked before commit.
            progress = self.store.cancel(
                operation_id, move_actor(access), self.clock_ms()
            )
            current = self.authorization.require(access, Scope.FILES_MOVE)
            self.store.progress(operation_id, move_actor(current))
            self.uow.commit()
            return move_progress_result(progress)
        except Exception:
            self.uow.rollback()
            raise
