"""Wire file-move execution to the canonical index and existing work queues."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.bootstrap.automation import build_automation_authorizer
from app.core.failure_diagnostics import RuntimeFailureDiagnostics
from app.core.time import now_timestamp_ms
from app.modules.automation.application.execution import RecheckMoveAccess
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.library.application.execute_file_moves import ExecuteFileMoveOperation
from app.modules.library.application.file_move_worker import FileMoveWorker
from app.modules.library.infrastructure.file_move_index import SqlAlchemyFileMoveIndex
from app.modules.library.infrastructure.file_move_io import SystemMovePublication
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.metadata.infrastructure.writeback_queue import (
    discard_relocated_writebacks,
)
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)


def build_file_move_worker(db: Session) -> FileMoveWorker:
    store = SqlAlchemyFileMoveOperations(db)
    files = SystemMovePublication()
    diagnostics = RuntimeFailureDiagnostics(
        logging.getLogger(__name__), "library", lambda: Session(db.get_bind())
    )
    return FileMoveWorker(
        store,
        ExecuteFileMoveOperation(
            store,
            files,
            SqlAlchemyFileMoveIndex(db),
            RecheckMoveAccess(
                build_automation_authorizer(db), SqlAlchemyAutomationSettings(db)
            ),
            SqlAlchemyLibraryImportTaskQueue(db).reconcile_relocation,
            lambda change: discard_relocated_writebacks(db, change),
            db,
            now_timestamp_ms,
            lambda: datetime.now(UTC),
            diagnostics,
        ),
        db,
        now_timestamp_ms,
        diagnostics,
    )
