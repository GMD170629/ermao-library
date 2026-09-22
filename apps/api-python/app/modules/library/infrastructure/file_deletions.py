"""Deletion journals and descriptor-anchored permanent deletion."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.file_lock import try_file_lock, unlock_file
from app.infrastructure.exclusive_rename import exclusive_rename
from app.infrastructure.file_operation_conflicts import file_operation_blocks_library
from app.models import Library, LibraryImportTask
from app.modules.library.application.file_deletions import DeletePlan, DeleteTarget
from app.modules.library.application.file_move_plans import MoveSource
from app.modules.library.domain.file_moves import FileMoveError, MoveInventory
from app.modules.library.infrastructure.file_delete_schema import FileDeletePlanRow
from app.modules.library.infrastructure.move_inventory import inspect_move_source
from app.modules.library.infrastructure.source_file_access import open_library_directory

_PLAN = TypeAdapter(DeletePlan)


class SqlAlchemyDeleteStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, plan: DeletePlan) -> None:
        row = self.db.get(FileDeletePlanRow, plan.id, populate_existing=True)
        if row is None:
            row = FileDeletePlanRow(
                id=plan.id, user_id=plan.user_id, grant_id=plan.grant_id
            )
            self.db.add(row)
        if plan.executing and not (row.payload or {}).get("executing"):
            # Acquire the SQLite writer transaction before checking other claims.
            row.payload = row.payload or {}
            flag_modified(row, "payload")
            self.db.flush()
            libraries = frozenset(t.source.library_id for t in plan.targets)
            busy = self.db.scalar(
                select(Library.id)
                .where(
                    Library.id.in_(libraries),
                    file_operation_blocks_library(Library.id, datetime.now(UTC)),
                )
                .limit(1)
            )
            importing = self.db.scalar(
                select(LibraryImportTask.id)
                .where(
                    LibraryImportTask.library_id.in_(libraries),
                    LibraryImportTask.state == "RUNNING",
                )
                .limit(1)
            )
            if busy or importing:
                raise FileMoveError("LIBRARY_BUSY")
        payload = _PLAN.dump_python(plan, mode="json")
        if row.payload and row.payload.get("cancelled"):
            payload["cancelled"] = True
        row.payload = payload

    def load(self, plan_id: str, user_id: str, grant_id: str) -> DeletePlan:
        row = self.db.scalar(
            select(FileDeletePlanRow)
            .where(
                FileDeletePlanRow.id == plan_id,
                FileDeletePlanRow.user_id == user_id,
                FileDeletePlanRow.grant_id == grant_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        return _PLAN.validate_python(row.payload)


class AnchoredDeleteFiles:
    def __init__(self, lock_root: Path) -> None:
        self.lock_root = lock_root

    @contextmanager
    def lock(self, plan_id: str) -> Iterator[None]:
        if not plan_id.isalnum():
            raise FileMoveError("INVALID_PLAN_ID")
        self.lock_root.mkdir(parents=True, exist_ok=True)
        with (self.lock_root / (plan_id + ".lock")).open("a+b") as stream:
            if not try_file_lock(stream, exclusive=True):
                raise FileMoveError("OPERATION_BUSY")
            try:
                yield
            finally:
                unlock_file(stream)

    def inspect(self, source: MoveSource) -> MoveInventory:
        return inspect_move_source(source.root, source.relative_path)

    def stage(self, target: DeleteTarget) -> None:
        source = target.source
        parent, _, name = source.relative_path.rpartition("/")
        stage_name = target.staging_path.rpartition("/")[2]
        expected = target.inventory.entries[0].identity
        with open_library_directory(source.root, parent) as directory:
            try:
                staged = os.stat(stage_name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                staged = None
            if staged is not None:
                if (staged.st_dev, staged.st_ino) != (expected.device, expected.inode):
                    raise FileMoveError("STAGING_CONFLICT")
                return
            if self.inspect(source) != target.inventory:
                raise FileMoveError("SOURCE_CHANGED")
            exclusive_rename(directory, name, directory, stage_name)
            os.fsync(directory)

    def erase(self, target: DeleteTarget) -> None:
        source = target.source
        for item in reversed(target.inventory.entries):
            suffix = item.relative_path[len(source.relative_path) :]
            relative = target.staging_path + suffix
            parent, _, name = relative.rpartition("/")
            try:
                with open_library_directory(source.root, parent) as directory:
                    try:
                        observed = os.stat(
                            name, dir_fd=directory, follow_symlinks=False
                        )
                    except FileNotFoundError:
                        continue
                    expected = item.identity
                    if (observed.st_dev, observed.st_ino) != (
                        expected.device,
                        expected.inode,
                    ):
                        raise FileMoveError("SOURCE_CHANGED")
                    if not item.directory and (
                        observed.st_size,
                        observed.st_mtime_ns,
                    ) != (expected.size, expected.mtime_ns):
                        raise FileMoveError("SOURCE_CHANGED")
                    if item.directory:
                        os.rmdir(name, dir_fd=directory)
                    else:
                        os.unlink(name, dir_fd=directory)
                    os.fsync(directory)
            except FileNotFoundError:
                continue
