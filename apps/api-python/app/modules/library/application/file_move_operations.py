"""Durable move submission and user-visible progress; execution is worker-owned."""

from dataclasses import dataclass
from typing import Protocol

from app.modules.library.application.file_move_plans import FileMovePlan, MoveActor
from app.modules.library.domain.file_moves import FileMoveError


@dataclass(frozen=True)
class FileMoveProgress:
    operation_id: str
    plan_id: str
    status: str
    cancel_requested: bool
    stages: tuple[str, ...]
    error_codes: tuple[str | None, ...]


class FileMoveOperationPort(Protocol):
    def save_plan(self, plan: FileMovePlan) -> None: ...
    def load_plan(self, plan_id: str, actor: MoveActor) -> FileMovePlan: ...
    def enqueue(
        self, plan: FileMovePlan, operation_id: str, request_id: str, now_ms: int
    ) -> str: ...
    def progress(self, operation_id: str, actor: MoveActor) -> FileMoveProgress: ...
    def cancel(
        self, operation_id: str, actor: MoveActor, now_ms: int
    ) -> FileMoveProgress: ...


def require_plan_access(plan: FileMovePlan, actor: MoveActor) -> None:
    if plan.actor.grant_id != actor.grant_id or plan.actor.user_id != actor.user_id:
        raise FileMoveError("RESOURCE_NOT_FOUND")
    for move in plan.moves:
        if (
            not {move.source.library_id, move.destination.library_id}
            <= actor.library_ids
        ):
            raise FileMoveError("RESOURCE_NOT_FOUND")
        if (
            move.source.library_id != move.destination.library_id
            and not actor.allow_cross_library
        ):
            raise FileMoveError("CROSS_LIBRARY_NOT_AUTHORIZED")


def move_progress_result(progress: FileMoveProgress) -> dict[str, object]:
    return {
        "operation_id": progress.operation_id,
        "plan_id": progress.plan_id,
        "status": progress.status,
        "cancel_requested": progress.cancel_requested,
        "completed": progress.stages.count("COMPLETED"),
        "cancelled": progress.stages.count("CANCELLED"),
        "failed": progress.stages.count("FAILED"),
        "recovery_required": progress.stages.count("RECOVERY_REQUIRED"),
        "targets": [
            {"index": index, "stage": stage, "error_code": error}
            for index, (stage, error) in enumerate(
                zip(progress.stages, progress.error_codes, strict=True)
            )
        ],
    }


def move_plan_result(plan: FileMovePlan) -> dict[str, object]:
    return {
        "plan_id": plan.id,
        "expires_at_ms": plan.expires_at_ms,
        "file_count": sum(move.inventory.file_count for move in plan.moves),
        "byte_count": sum(move.inventory.byte_count for move in plan.moves),
        "blocking_errors": [],
        "moves": [
            {
                "source_node_id": move.source.node_id
                if move.companion_owner is None
                else None,
                "companion_owner_node_id": move.companion_owner.node_id
                if move.companion_owner
                else None,
                "companion": move.companion_owner is not None,
                "source_library_id": move.source.library_id,
                "source_relative_path": move.source.relative_path,
                "destination_library_id": move.destination.library_id,
                "destination_relative_path": move.destination.relative_path,
                "source_revision": move.source.revision,
                "book_ids": list(move.source.book_ids),
                "cross_device": move.cross_device,
                "visibility_changes": move.source.library_id
                != move.destination.library_id,
                "create_directories": list(
                    move.destination_inspection.missing_directories
                ),
                "files": [
                    item.relative_path
                    for item in move.inventory.entries
                    if not item.directory
                ],
                "recovery_strategy": "verified_copy_publish_index_cleanup"
                if move.cross_device
                else "exclusive_rename_index",
            }
            for move in plan.moves
        ],
    }
