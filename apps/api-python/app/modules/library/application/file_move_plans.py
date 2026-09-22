"""Freeze authorized moves without creating or moving any library file."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from app.modules.library.domain.file_moves import (
    MAX_BYTES,
    MAX_FILES,
    FileIdentity,
    FileMoveError,
    MoveInventory,
    MoveRequest,
    case_only_path,
    validate_move_set,
)


@dataclass(frozen=True)
class MoveActor:
    user_id: str
    grant_id: str
    library_ids: frozenset[str]
    allow_cross_library: bool


@dataclass(frozen=True)
class MoveSource:
    node_id: str
    library_id: str
    relative_path: str
    root: Path
    revision: str
    book_ids: tuple[str, ...]
    complete_book_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MoveDestination:
    library_id: str
    root: Path
    relative_path: str
    identity_policy: Literal["PRESERVE_IDENTITY", "REIMPORT"] = "PRESERVE_IDENTITY"
    topology_revision: str = ""


@dataclass(frozen=True)
class DestinationInspection:
    missing_directories: tuple[str, ...]
    device: int
    parent_inode: int
    parent_relative_path: str


@dataclass(frozen=True)
class CreatedMoveDirectory:
    relative_path: str
    identity: FileIdentity


@dataclass(frozen=True)
class PlannedMove:
    source: MoveSource
    destination: MoveDestination
    inventory: MoveInventory
    destination_inspection: DestinationInspection
    companion_owner: MoveSource | None = None

    @property
    def case_only(self) -> bool:
        return self.source.library_id == self.destination.library_id and case_only_path(
            self.source.relative_path, self.destination.relative_path
        )


@dataclass(frozen=True)
class FileMovePlan:
    id: str
    actor: MoveActor
    created_at_ms: int
    expires_at_ms: int
    moves: tuple[PlannedMove, ...]
    execution_version: int = 1


class MoveTopologyPort(Protocol):
    def source(self, node_id: str, library_ids: frozenset[str]) -> MoveSource: ...
    def destination(
        self, source: MoveSource, request: MoveRequest, library_ids: frozenset[str]
    ) -> MoveDestination:
        """Freeze target topology and the identity policy for a complete unit."""
        ...


class MoveInspectionPort(Protocol):
    def companions(
        self, source: MoveSource, destination: MoveDestination, *, directory: bool
    ) -> tuple[tuple[str, str], ...]: ...
    def source(self, root: Path, relative_path: str) -> MoveInventory: ...
    def destination(
        self, root: Path, relative_path: str, *, existing_source: str | None = None
    ) -> DestinationInspection: ...


@dataclass(frozen=True)
class PrepareFileMovePlan:
    topology: MoveTopologyPort
    inspection: MoveInspectionPort
    clock_ms: Callable[[], int]
    new_id: Callable[[], str]

    def execute(
        self, actor: MoveActor, requests: tuple[MoveRequest, ...]
    ) -> FileMovePlan:
        if not 1 <= len(requests) <= 100:
            raise FileMoveError("INVALID_TARGET_COUNT")
        sources = tuple(
            self.topology.source(item.node_id, actor.library_ids) for item in requests
        )
        for source, request in zip(sources, requests, strict=True):
            if (
                source.library_id not in actor.library_ids
                or request.destination_library_id not in actor.library_ids
            ):
                raise FileMoveError("RESOURCE_NOT_FOUND")
            if (
                source.library_id != request.destination_library_id
                and not actor.allow_cross_library
            ):
                raise FileMoveError("CROSS_LIBRARY_NOT_AUTHORIZED")
        validate_move_set(
            tuple((item.library_id, item.relative_path) for item in sources),
            tuple(
                (item.destination_library_id, item.destination_relative_path)
                for item in requests
            ),
        )
        # Complete topology authorization for every item before reading files.
        destinations = tuple(
            self.topology.destination(source, request, actor.library_ids)
            for source, request in zip(sources, requests, strict=True)
        )
        plan_id = self.new_id()
        moves: list[PlannedMove] = []
        files = size = 0
        for source, destination in zip(sources, destinations, strict=True):
            inventory = self.inspection.source(source.root, source.relative_path)
            target = self.inspection.destination(
                destination.root,
                destination.relative_path,
                existing_source=source.relative_path
                if source.library_id == destination.library_id
                and case_only_path(source.relative_path, destination.relative_path)
                else None,
            )
            files += inventory.file_count
            size += inventory.byte_count
            if files > MAX_FILES or size > MAX_BYTES:
                raise FileMoveError("INVENTORY_LIMIT")
            moves.append(
                PlannedMove(
                    source,
                    destination,
                    inventory,
                    target,
                )
            )
        expanded: list[PlannedMove] = []
        for move in moves:
            if move.destination.identity_policy == "REIMPORT":
                # Reimport only the selected file/subtree. Shared or adjacent
                # metadata belongs to the source book and must stay there.
                expanded.append(move)
                continue
            for source_path, target_path in self.inspection.companions(
                move.source,
                move.destination,
                directory=move.inventory.entries[0].directory,
            ):
                companion_source = replace(move.source, relative_path=source_path)
                companion_destination = replace(
                    move.destination, relative_path=target_path
                )
                inventory = self.inspection.source(companion_source.root, source_path)
                if inventory.entries[0].directory:
                    raise FileMoveError("SIDECAR_REGULAR_FILE_REQUIRED")
                files += inventory.file_count
                size += inventory.byte_count
                if files > MAX_FILES or size > MAX_BYTES:
                    raise FileMoveError("INVENTORY_LIMIT")
                expanded.append(
                    PlannedMove(
                        companion_source,
                        companion_destination,
                        inventory,
                        self.inspection.destination(
                            companion_destination.root, target_path
                        ),
                        move.source,
                    )
                )
            expanded.append(move)
        validate_move_set(
            tuple(
                (move.source.library_id, move.source.relative_path) for move in expanded
            ),
            tuple(
                (move.destination.library_id, move.destination.relative_path)
                for move in expanded
            ),
            expanded=True,
        )
        now = self.clock_ms()
        return FileMovePlan(
            plan_id, actor, now, now + 15 * 60_000, tuple(expanded), execution_version=3
        )
