"""Process a claimed import task through media import and post-success hooks."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
)
from app.modules.imports.application.errors import (
    LibraryDeletedDuringImportError,
)
from app.modules.imports.application.ports import (
    ImportMetadataObserver,
    ImportPipeline,
    ImportTaskStore,
    ImportUnitOfWork,
)


def _ensure_library_exists(
    store: ImportTaskStore,
    library_id: str | None,
) -> None:
    if library_id is not None and not store.library_exists(
        library_id
    ):
        raise LibraryDeletedDuringImportError


def process_import_task(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    pipeline: ImportPipeline,
    settings: ImportRuntimeConfig,
    task: ImportTaskDTO,
    metadata_observer: ImportMetadataObserver | None = None,
    *,
    now: int,
) -> ImportResult:
    try:
        _ensure_library_exists(store, task.library_id)
        unit_of_work.release()
        result = pipeline.import_managed_book(
            settings,
            ImportOptions(
                source_file_path=Path(task.source_path),
                original_name=task.original_name,
                requested_title=task.requested_title,
                requested_author=task.requested_author,
                origin=task.origin or "MANUAL",
                library_id=task.library_id,
                media_kind_policy=task.media_kind_policy,
                import_task_id=task.id,
                expected_lease_owner=task.lease_owner,
            ),
        )
        _ensure_library_exists(store, task.library_id)
        store.mark_download_completed(
            source_path=task.source_path,
            book_id=result.work_id,
            updated_at=now,
        )
        if metadata_observer is not None:
            metadata_observer.schedule(result)
        pipeline.complete_import()
        unit_of_work.commit()
        return result
    except Exception:
        unit_of_work.rollback()
        raise
