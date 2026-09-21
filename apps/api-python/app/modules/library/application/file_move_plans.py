"""Freeze authorized moves without creating or moving any library file."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.modules.library.domain.file_moves import (
    MAX_BYTES,
    MAX_FILES,
    FileIdentity,
    FileMoveError,
    MoveInventory,
    MoveRequest,
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


@dataclass(frozen=True)
class MoveDestination:
    library_id: str
    root: Path
    relative_path: str


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
    staging_relative_path: str | None = None
    backup_relative_path: str | None = None

    @property
    def cross_device(self) -> bool:
        return (
            self.inventory.entries[0].identity.device
            != self.destination_inspection.device
        )


@dataclass(frozen=True)
class CopiedContent:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class PreparedMoveCopy:
    inventory: MoveInventory
    contents: tuple[CopiedContent, ...]


@dataclass(frozen=True)
class StagedMoveSource:
    relative_path: str
    identity: FileIdentity


@dataclass(frozen=True)
class FileMovePlan:
    id: str
    actor: MoveActor
    created_at_ms: int
    expires_at_ms: int
    moves: tuple[PlannedMove, ...]


class MoveTopologyPort(Protocol):
    def source(self, node_id: str, library_ids: frozenset[str]) -> MoveSource: ...
    def destination(
        self, source: MoveSource, request: MoveRequest, library_ids: frozenset[str]
    ) -> MoveDestination:
        """Reject moves changing book/resource ownership or organization mode."""
        ...


class MoveInspectionPort(Protocol):
    def source(self, root: Path, relative_path: str) -> MoveInventory: ...
    def destination(self, root: Path, relative_path: str) -> DestinationInspection: ...


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
                destination.root, destination.relative_path
            )
            files += inventory.file_count
            size += inventory.byte_count
            if files > MAX_FILES or size > MAX_BYTES:
                raise FileMoveError("INVENTORY_LIMIT")
            slot = hashlib.sha256(f"{plan_id}:{len(moves)}".encode()).hexdigest()[:32]
            moves.append(
                PlannedMove(
                    source,
                    destination,
                    inventory,
                    target,
                    f".ermao-mcp-{slot}-target",
                    f".ermao-mcp-{slot}-source",
                )
            )
        now = self.clock_ms()
        return FileMovePlan(plan_id, actor, now, now + 15 * 60_000, tuple(moves))
