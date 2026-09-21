"""Update the canonical source tree in place after journalled publication."""

from datetime import datetime

from sqlalchemy import insert, or_, select, update
from sqlalchemy.orm import Session

from app.models.common import cuid
from app.modules.library.application.file_move_plans import (
    CreatedMoveDirectory,
    PlannedMove,
)
from app.modules.library.domain.file_moves import FileMoveError
from app.modules.library.domain.source_nodes import SourceNodeRelativePath
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.library.infrastructure.readable_resource_schema import (
    LibrarySourceNode,
)


class SqlAlchemyFileMoveIndex:
    def __init__(self, db: Session) -> None:
        self._db = db

    def apply(
        self,
        move: PlannedMove,
        now: datetime,
        directories: tuple[CreatedMoveDirectory, ...] = (),
    ) -> tuple[str, ...]:
        libraries = frozenset({move.source.library_id, move.destination.library_id})
        current = SqlAlchemyMoveTopology(self._db).source(
            move.source.node_id, libraries
        )
        if current.revision != move.source.revision:
            raise FileMoveError("SOURCE_INDEX_CHANGED")
        parent_paths = {directory.relative_path for directory in directories}
        parent_paths.update(path.rpartition("/")[0] for path in tuple(parent_paths))
        existing_nodes = tuple(
            self._db.execute(
                select(
                    LibrarySourceNode.relative_path,
                    LibrarySourceNode.id,
                    LibrarySourceNode.physical_kind,
                ).where(
                    LibrarySourceNode.library_id == move.destination.library_id,
                    LibrarySourceNode.relative_path.in_(parent_paths),
                )
            )
        )
        parent_ids = {
            path: node_id
            for path, node_id, kind in existing_nodes
            if kind == "DIRECTORY"
        }
        occupied = {path for path, _, kind in existing_nodes if kind != "DIRECTORY"}
        new_directories: list[dict[str, object]] = []
        for directory in directories:
            path = SourceNodeRelativePath(directory.relative_path)
            if path.value in occupied:
                raise FileMoveError("DESTINATION_PARENT_NOT_INDEXED")
            if path.value in parent_ids:
                continue
            parent_node_id = parent_ids.get(path.parent_relative_path or "")
            if path.parent_relative_path is not None and parent_node_id is None:
                raise FileMoveError("DESTINATION_PARENT_NOT_INDEXED")
            node_id = cuid()
            new_directories.append(
                {
                    "id": node_id,
                    "library_id": move.destination.library_id,
                    "parent_id": parent_node_id,
                    "parent_physical_kind": "DIRECTORY" if parent_node_id else None,
                    "relative_path": path.value,
                    "path_key": path.path_key,
                    "name": path.name,
                    "physical_kind": "DIRECTORY",
                    "observed_size_bytes": None,
                    "observed_mtime_ns": directory.identity.mtime_ns,
                    "observed_at": now,
                }
            )
            parent_ids[path.value] = node_id
        if new_directories:
            self._db.execute(
                insert(LibrarySourceNode).execution_options(render_nulls=True),
                new_directories,
            )
        parent_path = SourceNodeRelativePath(
            move.destination.relative_path
        ).parent_relative_path
        parent_id: str | None = None
        if parent_path is not None:
            parent_id = self._db.scalar(
                select(LibrarySourceNode.id).where(
                    LibrarySourceNode.library_id == move.destination.library_id,
                    LibrarySourceNode.relative_path == parent_path,
                    LibrarySourceNode.physical_kind == "DIRECTORY",
                )
            )
            if parent_id is None:
                raise FileMoveError("DESTINATION_PARENT_NOT_INDEXED")
        nodes = self._db.execute(
            select(
                LibrarySourceNode.id,
                LibrarySourceNode.relative_path,
            )
            .where(
                LibrarySourceNode.library_id == move.source.library_id,
                or_(
                    LibrarySourceNode.id == move.source.node_id,
                    LibrarySourceNode.relative_path.startswith(
                        move.source.relative_path + "/", autoescape=True
                    ),
                ),
            )
            .order_by(LibrarySourceNode.relative_path)
        ).all()
        for node_id, old_path in nodes:
            path = SourceNodeRelativePath(
                move.destination.relative_path
                + old_path[len(move.source.relative_path) :]
            )
            changes: dict[str, object] = {
                "library_id": move.destination.library_id,
                "relative_path": path.value,
                "path_key": path.path_key,
                "name": path.name,
                "updated_at": now,
            }
            if node_id == move.source.node_id:
                changes.update(
                    parent_id=parent_id,
                    parent_physical_kind="DIRECTORY" if parent_id else None,
                )
            # Existing composite ON UPDATE CASCADE constraints preserve Book,
            # Resource, Asset, and node-bound import IDs and their library scope.
            self._db.execute(
                update(LibrarySourceNode)
                .where(LibrarySourceNode.id == node_id)
                .values(**changes)
            )
        self._db.flush()
        return tuple(node_id for node_id, _ in nodes)
