"""Process a claimed import task through media import and post-success hooks."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
)
from app.modules.imports.application.ports import (
    ImportPipeline,
    ImportTaskStore,
    ImportUnitOfWork,
)


def process_import_task(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    pipeline: ImportPipeline,
    settings: ImportRuntimeConfig,
    task: ImportTaskDTO,
    *,
    now: int,
) -> ImportResult:
    try:
        result = pipeline.import_managed_book(
            settings,
            ImportOptions(
                source_file_path=Path(task.source_path),
                original_name=task.original_name,
                requested_title=task.requested_title,
                requested_author=task.requested_author,
                origin=task.origin or "MANUAL",
                monitor_folder_id=task.monitor_folder_id,
                import_task_id=task.id,
                requested_work_id=task.work_id,
                expected_lease_owner=task.lease_owner,
            ),
        )
        store.link_work_to_monitor_shelf(
            task.monitor_folder_id,
            result.work_id,
            created_at=now,
        )
        store.mark_download_completed(
            source_path=task.source_path,
            book_id=result.work_id,
            updated_at=now,
        )
        unit_of_work.commit()
        pipeline.finalize_publications()
        return result
    except Exception:
        unit_of_work.rollback()
        pipeline.rollback_publications()
        raise
