from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models import Library, LibraryImportTask
from app.modules.imports.infrastructure.library_queries import (
    list_import_tasks_page,
)
from app.modules.imports.presentation.mappers import import_task_view


def test_import_task_page_has_fixed_query_count(db_session: Session) -> None:
    now = datetime.now(UTC)
    task_count = 100_000
    db_session.add(
        Library(
            id="import-scale-library",
            name="Import scale",
            root_path="/tmp/import-scale-library",
            organization_mode="FLAT",
        )
    )
    db_session.flush()
    for start in range(0, task_count, 1_000):
        stop = min(task_count, start + 1_000)
        db_session.execute(
            insert(LibraryImportTask),
            [
                {
                    "id": f"import-scale-{index:06d}",
                    "kind": "SCAN_LIBRARY",
                    "library_id": "import-scale-library",
                    "state": "FAILED" if index % 4 == 0 else "SUCCEEDED",
                    "created_at": now - timedelta(seconds=index),
                    "error_summary": "PARSE_FAILED" if index % 4 == 0 else None,
                }
                for index in range(start, stop)
            ],
        )
    db_session.commit()
    context = AuthorizationContext(
        user_id="import-scale-admin",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )
    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        tasks, total, summary = list_import_tasks_page(
            db_session,
            context,
            page=1,
            page_size=10,
        )
        views = [import_task_view(task) for task in tasks]
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert total == task_count
    assert summary == {
        "queued": 0,
        "running": 0,
        "completed": 75_000,
        "failed": 25_000,
    }
    assert len(views) == 10
    assert all(
        set(view)
        == {
            "id",
            "kind",
            "libraryId",
            "libraryName",
            "resourceId",
            "resourceTitle",
            "sourceNodeId",
            "sourceName",
            "sourceRelativePath",
            "bookTitle",
            "role",
            "state",
            "errorSummary",
            "createdAt",
            "startedAt",
            "finishedAt",
        }
        for view in views
    )
    assert select_count <= 5
