from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.imports import fail_claimed_import_task, process_import_task
from app.core.config import Settings
from app.models.import_pipeline import ImportTask
from app.models.settings import MonitorFolder
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.errors import (
    MonitorFolderDeletedDuringImportError,
)
from app.modules.imports.presentation.mappers import friendly_import_error


def test_deleted_monitor_folder_has_terminal_user_guidance() -> None:
    assert friendly_import_error(None, "MONITOR_FOLDER_NOT_FOUND") == (
        "监控文件夹已被删除，本次导入任务已结束。"
    )


def test_claimed_import_fails_terminally_when_monitor_folder_is_deleted(
    db_session: Session,
    test_settings: Settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"queued")
    folder = MonitorFolder(
        id="folder-deleted-during-import",
        name="Inbox",
        root_path=str(tmp_path),
    )
    task_row = ImportTask(
        id="task-with-deleted-monitor-folder",
        monitor_folder_id=folder.id,
        origin="WATCH",
        status="PARSING",
        original_name=source.name,
        source_path=str(source),
        lease_owner="worker-1",
    )
    db_session.add_all((folder, task_row))
    db_session.commit()
    task = ImportTaskDTO(
        id=task_row.id,
        monitor_folder_id=task_row.monitor_folder_id,
        origin=task_row.origin,
        status=task_row.status,
        original_name=task_row.original_name,
        source_path=task_row.source_path,
        lease_owner=task_row.lease_owner,
    )

    db_session.delete(folder)
    db_session.commit()

    with pytest.raises(MonitorFolderDeletedDuringImportError) as captured:
        process_import_task(db_session, test_settings, task)
    assert fail_claimed_import_task(db_session, task, captured.value) is True

    stored = db_session.scalar(select(ImportTask).where(ImportTask.id == task.id))
    assert stored is not None
    assert stored.status == "FAILED"
    assert stored.progress == 100
    assert stored.error_code == "MONITOR_FOLDER_NOT_FOUND"
    assert stored.retryable is False
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None
    assert stored.finished_at is not None
