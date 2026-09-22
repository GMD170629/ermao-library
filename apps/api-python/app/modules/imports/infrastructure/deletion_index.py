"""Reconcile a deleted source through the existing scoped import queue."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import LibraryImportTask
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.library.public import MoveSource


class DeletedSourceIndex:
    def __init__(self, db: Session, delete_node: Callable[[str], None]) -> None:
        self.db = db
        self.delete_node = delete_node

    def enqueue(self, source: MoveSource) -> str:
        # The user explicitly deleted this frozen source: clean its exact index
        # through the existing use case, including when the library is now empty.
        self.delete_node(source.node_id)
        task, _ = SqlAlchemyLibraryImportTaskQueue(self.db).request_library_scan(
            source.library_id,
            missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
            scan_scopes=(
                ScanScope(
                    relative_path=source.relative_path.rpartition("/")[0],
                    recursive=False,
                ),
            ),
        )
        return task.id

    def status(self, task_id: str) -> str:
        task = self.db.get(LibraryImportTask, task_id, populate_existing=True)
        return task.state if task is not None else "FAILED"
