"""Force a claimed import task into a terminal failure state."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.commands import (
    commit_import_checkpoint,
    reset_failed_import_checkpoint,
)
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.application.ports import (
    ImportSourceProbe,
    ImportTaskStore,
    ImportUnitOfWork,
)


def fail_claimed_import_task(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    task: ImportTaskDTO,
    error: BaseException,
    *,
    now: int,
    source_probe: ImportSourceProbe,
) -> bool:
    """Force an already claimed task into a terminal state after an unexpected worker error."""

    reset_failed_import_checkpoint(unit_of_work)
    source = Path(task.source_path or "")
    source_missing = not source_probe.exists(source)
    error_code = "SOURCE_NOT_FOUND" if source_missing else "IMPORT_WORKER_FAILED"
    error_summary = (
        f"导入源已不存在：{source}"
        if source_missing
        else str(error) or error.__class__.__name__
    )
    failed = store.fail_claimed(
        task,
        error_code=error_code,
        error_summary=error_summary,
        message=(
            "导入源文件或目录不存在，任务已结束"
            if source_missing
            else "导入工作进程异常，任务已结束"
        ),
        retryable=not source_missing,
        now=now,
    )
    if failed:
        store.stage_failure_event(task, error_summary=error_summary, now=now)
    commit_import_checkpoint(unit_of_work)
    return failed
