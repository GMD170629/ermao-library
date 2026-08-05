from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.import_pipeline import ImportLog, ImportTask
from app.modules.imports.infrastructure.import_http import (
    hydrate_import_task_page,
    list_import_tasks_page,
)
from app.modules.imports.presentation.mappers import import_task_view


def test_import_task_page_has_fixed_query_count(db_session: Session) -> None:
    now = datetime.now(UTC)
    task_count = 100_000
    for start in range(0, task_count, 1_000):
        stop = min(task_count, start + 1_000)
        db_session.execute(
            insert(ImportTask),
            [
                {
                    "id": f"import-scale-{index:06d}",
                    "origin": "MANUAL",
                    "status": "FAILED" if index % 4 == 0 else "COMPLETED",
                    "source_path": f"/missing/import-scale-{index:06d}.epub",
                    "created_at": now - timedelta(seconds=index),
                    "updated_at": now - timedelta(seconds=index),
                }
                for index in range(start, stop)
            ],
        )
        db_session.execute(
            insert(ImportLog),
            [
                {
                    "id": f"import-scale-log-{index:06d}",
                    "import_task_id": f"import-scale-{index:06d}",
                    "level": "info",
                    "message": "completed",
                    "created_at": now - timedelta(seconds=index),
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
        monitor_folder_ids=(),
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
        tasks = hydrate_import_task_page(db_session, tasks, log_limit=20)
        views = [import_task_view(db_session, task, log_limit=20) for task in tasks]
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert total == task_count
    assert summary == {"completed": 75_000, "failed": 25_000}
    assert len(views) == 10
    assert all(len(view["logs"]) == 1 for view in views)
    assert select_count <= 10
