"""Cookie-session history and cancellation; never an alternative execution path."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.modules.automation.application.file_moves import move_actor
from app.modules.automation.application.grants import (
    AutomationIdentityPort,
    GrantStore,
    GrantUnitOfWork,
)
from app.modules.automation.application.operations import AutomationOperations
from app.modules.automation.domain.access import (
    ALL_SCOPES,
    AutomationAccessError,
    EffectiveAccess,
    Scope,
    effective_access,
)
from app.modules.library.public import FileMoveError
from app.modules.metadata.public import StandardMetadataError


@dataclass(frozen=True)
class OperationReference:
    operation_id: str
    grant_id: str
    kind: Literal["file_move", "metadata_writeback"]
    created_at_ms: int


class OperationHistoryPort(Protocol):
    def recent(
        self, user_id: str, library_ids: frozenset[str]
    ) -> tuple[OperationReference, ...]: ...
    def get(self, operation_id: str, user_id: str) -> OperationReference | None: ...


@dataclass(frozen=True)
class OperationTargetView:
    stage: str
    relative_path: str
    destination_relative_path: str | None
    error_code: str | None


@dataclass(frozen=True)
class ManagedOperationView:
    operation_id: str
    grant_id: str
    kind: str
    created_at_ms: int
    status: str
    cancel_requested: bool
    total_targets: int
    targets: tuple[OperationTargetView, ...]


@dataclass(frozen=True)
class ManageAutomationOperations:
    history: OperationHistoryPort
    grants: GrantStore
    identities: AutomationIdentityPort
    operations: AutomationOperations
    uow: GrantUnitOfWork
    clock_ms: Callable[[], int]

    def _access(self, user_id: str, reference: OperationReference) -> EffectiveAccess:
        actor = self.identities.current_actor(user_id)
        grant = self.grants.by_id(reference.grant_id)
        if actor is None or not actor.active:
            raise AutomationAccessError("UNAUTHORIZED")
        if grant is None or grant.user_id != user_id:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")
        # Revocation/disabled service blocks execution, not an owner's ability to
        # inspect or cancel existing work under their current account authority.
        return effective_access(
            grant_id=grant.id,
            user_id=user_id,
            permissions=grant.permissions,
            actor=actor,
            enabled_scopes=ALL_SCOPES,
        )

    def get(self, user_id: str, operation_id: str) -> ManagedOperationView:
        reference = self.history.get(operation_id, user_id)
        if reference is None:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")
        access = self._access(user_id, reference)
        if reference.kind == "file_move":
            access.require(Scope.FILES_MOVE)
            progress = self.operations.moves.store.progress(
                operation_id, move_actor(access)
            )
            plan = self.operations.moves.store.load_plan(
                progress.plan_id, move_actor(access)
            )
            targets = tuple(
                OperationTargetView(
                    stage,
                    move.source.relative_path,
                    move.destination.relative_path,
                    error,
                )
                for move, stage, error in zip(
                    plan.moves[:50],
                    progress.stages[:50],
                    progress.error_codes[:50],
                    strict=True,
                )
            )
            return ManagedOperationView(
                operation_id,
                reference.grant_id,
                reference.kind,
                reference.created_at_ms,
                progress.status,
                progress.cancel_requested,
                len(plan.moves),
                targets,
            )
        self.operations.writebacks.progress(access, operation_id)
        metadata_progress = self.operations.writebacks.store.progress(
            operation_id, access.grant_id, access.user_id
        )
        states = set(metadata_progress.stages)
        status = (
            "RECOVERY_REQUIRED"
            if "RECOVERY_REQUIRED" in states
            else (
                "COMPLETED"
                if states == {"COMPLETED"}
                else "CANCELLED"
                if states == {"CANCELLED"}
                else "FAILED"
                if states == {"FAILED"}
                else "PARTIAL"
                if states <= {"COMPLETED", "FAILED", "CANCELLED"}
                else "QUEUED"
                if states == {"QUEUED"}
                else "RUNNING"
            )
        )
        targets = tuple(
            OperationTargetView(stage, target.file.relative_path, None, error)
            for target, stage, error in zip(
                metadata_progress.plan.targets,
                metadata_progress.stages,
                metadata_progress.errors,
                strict=True,
            )
        )
        return ManagedOperationView(
            operation_id,
            reference.grant_id,
            reference.kind,
            reference.created_at_ms,
            status,
            metadata_progress.cancel_requested,
            len(targets),
            targets,
        )

    def recent(self, user_id: str) -> tuple[ManagedOperationView, ...]:
        actor = self.identities.current_actor(user_id)
        if actor is None or not actor.active:
            raise AutomationAccessError("UNAUTHORIZED")
        if not actor.can_manage_system:
            return ()
        results = []
        for reference in self.history.recent(user_id, actor.library_ids):
            try:
                results.append(self.get(user_id, reference.operation_id))
            except (AutomationAccessError, FileMoveError, StandardMetadataError):
                continue  # Current scope loss hides the whole operation, not a partial count.
        return tuple(results)

    def cancel(self, user_id: str, operation_id: str) -> ManagedOperationView:
        reference = self.history.get(operation_id, user_id)
        if reference is None:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")
        try:
            access = self._access(user_id, reference)
            self.get(user_id, operation_id)
            if reference.kind == "file_move":
                self.operations.moves.store.cancel(
                    operation_id, move_actor(access), self.clock_ms()
                )
            else:
                self.operations.writebacks.store.cancel(
                    operation_id, access.grant_id, access.user_id, self.clock_ms()
                )
            result = self.get(user_id, operation_id)
            self.uow.commit()
            return result
        except Exception:
            self.uow.rollback()
            raise
