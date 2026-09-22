"""Authorized permanent deletion tasks using the existing filesystem capability."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Protocol

from app.contracts.diagnostics import FailureDiagnostics
from app.modules.library.application.file_move_plans import MoveSource
from app.modules.library.application.source_browser import SourceAccessError
from app.modules.library.domain.file_moves import (
    MAX_BYTES,
    MAX_FILES,
    MAX_TARGETS,
    FileMoveError,
    MoveInventory,
)


@dataclass(frozen=True)
class DeleteTarget:
    source: MoveSource
    inventory: MoveInventory
    staging_path: str | None = None  # Read-only compatibility for legacy journals.
    stage: str = "QUEUED"
    error: str | None = None
    index_task_id: str | None = None


@dataclass(frozen=True)
class DeletePlan:
    id: str
    user_id: str
    grant_id: str
    created_at_ms: int
    expires_at_ms: int
    targets: tuple[DeleteTarget, ...]
    executing: bool = False
    cancelled: bool = False
    execution_version: int = 1


class DeleteStore(Protocol):
    def save(self, plan: DeletePlan) -> None: ...
    def load(self, plan_id: str, user_id: str, grant_id: str) -> DeletePlan: ...


class DeleteUnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class DeleteFiles(Protocol):
    def inspect(self, source: MoveSource) -> MoveInventory: ...
    def lock(self, plan_id: str) -> AbstractContextManager[None]: ...
    def validate(self, target: DeleteTarget) -> None: ...
    def delete(self, target: DeleteTarget) -> None: ...


class DeleteAuthorization(Protocol):
    def library_ids(self) -> frozenset[str]:
        """Recheck current delete authorization and return the allowed scope."""
        ...


class FileDeletions:
    def __init__(
        self,
        topology: Callable[[str, frozenset[str]], MoveSource],
        store: DeleteStore,
        uow: DeleteUnitOfWork,
        files: DeleteFiles,
        reindex: Callable[[MoveSource], str],
        index_status: Callable[[str], str],
        clock: Callable[[], int],
        new_id: Callable[[], str],
        diagnostics: FailureDiagnostics,
    ) -> None:
        self.topology, self.store, self.files = topology, store, files
        self.uow = uow
        self.reindex, self.clock, self.new_id = reindex, clock, new_id
        self.index_status = index_status
        self.diagnostics = diagnostics

    def plan(
        self,
        user_id: str,
        grant_id: str,
        libraries: frozenset[str],
        node_ids: tuple[str, ...],
    ) -> DeletePlan:
        if not 1 <= len(node_ids) <= MAX_TARGETS or len(set(node_ids)) != len(node_ids):
            raise FileMoveError("INVALID_TARGET_COUNT")
        plan_id = self.new_id()
        targets: list[DeleteTarget] = []
        for node_id in node_ids:
            source = self.topology(node_id, libraries)
            inventory = self.files.inspect(source)
            targets.append(DeleteTarget(source, inventory))
        paths = [
            (target.source.library_id, target.source.relative_path)
            for target in targets
        ]
        if any(
            a == b and (x == y or x.startswith(y + "/") or y.startswith(x + "/"))
            for i, (a, x) in enumerate(paths)
            for b, y in paths[i + 1 :]
        ):
            raise FileMoveError("OVERLAPPING_TARGETS")
        if sum(len(t.inventory.entries) for t in targets) > MAX_FILES:
            raise FileMoveError("FILE_LIMIT")
        if sum(t.inventory.byte_count for t in targets) > MAX_BYTES:
            raise FileMoveError("BYTE_LIMIT")
        now = self.clock()
        plan = DeletePlan(
            plan_id,
            user_id,
            grant_id,
            now,
            now + 900000,
            tuple(targets),
            execution_version=2,
        )
        self.store.save(plan)
        self.uow.commit()
        return plan

    def observed(self, plan: DeletePlan) -> DeletePlan:
        targets = tuple(
            replace(
                target,
                stage="COMPLETED"
                if self.index_status(target.index_task_id) == "SUCCEEDED"
                else "INDEX_FAILED"
                if self.index_status(target.index_task_id) == "FAILED"
                else "INDEX_PENDING",
            )
            if target.stage == "INDEX_PENDING" and target.index_task_id
            else target
            for target in plan.targets
        )
        return replace(plan, targets=targets)

    def execute(
        self,
        plan_id: str,
        user_id: str,
        grant_id: str,
        authorization: DeleteAuthorization,
    ) -> DeletePlan:
        with self.files.lock(plan_id):
            plan = self.store.load(plan_id, user_id, grant_id)
            if plan.execution_version != 2:
                raise FileMoveError("DELETE_PLAN_REQUIRES_REFRESH")
            if not plan.executing and plan.expires_at_ms <= self.clock():
                raise FileMoveError("PLAN_EXPIRED")
            plan = replace(plan, executing=True)
            step = "save_state"
            self.store.save(plan)
            step = "commit"
            self.uow.commit()
            for ordinal, original in enumerate(plan.targets):
                if original.stage in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELLED",
                    "INDEX_PENDING",
                    "INDEX_FAILED",
                }:
                    continue
                target = original
                step = "load_target"
                try:
                    fresh = self.store.load(plan_id, user_id, grant_id)
                    if target.stage == "DELETING":
                        diagnostic = self.diagnostics.prepare(
                            FileMoveError(
                                "Target was already DELETING at attempt start; the previous deletion result was not provided"
                            ),
                            event="file_delete.previous_result_unavailable",
                            context={
                                "operation_id": plan_id,
                                "target_ordinal": ordinal,
                                "stage": target.stage,
                                "step": "inspect_recovery_state",
                            },
                        )
                        self.uow.rollback()
                        self.diagnostics.persist(diagnostic)
                        # The previous process may already have removed this path.
                        # A repeated call must never delete a new same-name source.
                        target = replace(
                            target, error=target.error or "DELETE_RESULT_UNCERTAIN"
                        )
                        plan = replace(
                            plan,
                            targets=plan.targets[:ordinal]
                            + (target,)
                            + plan.targets[ordinal + 1 :],
                        )
                        self.store.save(plan)
                        self.uow.commit()
                        continue
                    if target.stage == "QUEUED" and fresh.cancelled:
                        target = replace(target, stage="CANCELLED")
                    else:
                        if target.stage == "QUEUED":
                            libraries = authorization.library_ids()
                            if target.source.library_id not in libraries:
                                raise FileMoveError("RESOURCE_NOT_FOUND")
                            if (
                                self.topology(target.source.node_id, libraries)
                                != target.source
                            ):
                                raise FileMoveError("SOURCE_CHANGED")
                            step = "validate_delete"
                            self.files.validate(target)
                            target = replace(target, stage="DELETING")
                            plan = replace(
                                plan,
                                targets=plan.targets[:ordinal]
                                + (target,)
                                + plan.targets[ordinal + 1 :],
                            )
                            step = "save_state"
                            self.store.save(plan)
                            step = "commit"
                            self.uow.commit()
                        if target.stage == "DELETING":
                            if (
                                target.source.library_id
                                not in authorization.library_ids()
                            ):
                                raise FileMoveError("RESOURCE_NOT_FOUND")
                            step = "delete_files"
                            self.files.delete(target)
                            target = replace(target, stage="FILES_DELETED")
                            plan = replace(
                                plan,
                                targets=plan.targets[:ordinal]
                                + (target,)
                                + plan.targets[ordinal + 1 :],
                            )
                            step = "save_state"
                            self.store.save(plan)
                            step = "commit"
                            self.uow.commit()
                        step = "reindex_deleted_source"
                        task_id = target.index_task_id or self.reindex(target.source)
                        target = replace(
                            target,
                            stage="INDEX_PENDING",
                            index_task_id=task_id,
                            error=None,
                        )
                except Exception as error:
                    diagnostic = self.diagnostics.prepare(
                        error,
                        event="file_delete.target_failed",
                        context={
                            "operation_id": plan_id,
                            "target_ordinal": ordinal,
                            "library_id": target.source.library_id,
                            "source_node_id": target.source.node_id,
                            "stage": target.stage,
                            "step": step,
                        },
                    )
                    try:
                        self.uow.rollback()
                    except Exception as rollback_error:
                        secondary = self.diagnostics.prepare(
                            rollback_error,
                            event="file_delete.rollback_failed",
                            context={
                                "operation_id": plan_id,
                                "target_ordinal": ordinal,
                                "step": "rollback",
                                "parent_diagnostic_id": diagnostic.diagnostic_id,
                            },
                        )
                        self.diagnostics.persist(secondary)
                        raise
                    finally:
                        self.diagnostics.persist(diagnostic)
                    if not isinstance(
                        error, (OSError, FileMoveError, SourceAccessError)
                    ):
                        raise
                    target = replace(
                        target,
                        error="DELETE_TARGET_FAILED",
                        stage="FAILED" if target.stage == "QUEUED" else target.stage,
                    )
                plan = replace(
                    plan,
                    targets=plan.targets[:ordinal]
                    + (target,)
                    + plan.targets[ordinal + 1 :],
                )
                step = "save_state"
                self.store.save(plan)
                step = "commit"
                self.uow.commit()
            return self.observed(plan)
