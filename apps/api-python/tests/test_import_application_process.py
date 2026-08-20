from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
)
from app.modules.imports.application.errors import (
    ImportExecutionError,
    LibraryDeletedDuringImportError,
)
from app.modules.imports.application.fail import fail_claimed_import_task
from app.modules.imports.application.process import process_import_task


@dataclass
class RecordingUnitOfWork:
    commits: int = 0
    rollbacks: int = 0
    releases: int = 0
    fail_commit: bool = False

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rollbacks += 1

    def release(self) -> None:
        self.releases += 1


class RecordingStore:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.library_available = True

    def library_exists(self, library_id: str) -> bool:
        self.calls.append("library")
        return self.library_available

    def mark_download_completed(
        self,
        *,
        source_path: str,
        book_id: str,
        updated_at: int,
    ) -> None:
        self.calls.append("download")
        if self.fail_at == "download":
            raise RuntimeError("download synchronization failed")


class RecordingPipeline:
    def __init__(
        self,
        *,
        fail: bool = False,
        after_import: Callable[[], None] | None = None,
    ) -> None:
        self.fail = fail
        self.after_import = after_import
        self.imports = 0
        self.options: ImportOptions | None = None
        self.completed = 0

    def import_managed_book(
        self,
        settings: object,
        options: ImportOptions,
    ) -> ImportResult:
        self.imports += 1
        self.options = options
        if self.fail:
            raise RuntimeError("final import synchronization failed")
        if self.after_import is not None:
            self.after_import()
        return ImportResult(
            book_id="work-1",
            work_id="work-1",
            version_id="media-version-1",
            volume_id="volume-1",
            title="测试书",
            type="EPUB",
            format="EPUB",
            total_units=1,
            import_status="completed",
            duplicate=False,
            merged=False,
            merge_reason="new",
        )

    def complete_import(self) -> None:
        self.completed += 1


def _task() -> ImportTaskDTO:
    return ImportTaskDTO(
        id="task-1",
        source_path="/tmp/book.epub",
        origin="WATCH",
        status="PARSING",
        library_id="folder-1",
        work_id="topology-work",
        volume_id="topology-volume",
    )


def test_process_import_commits_final_writes_once_after_post_success_hooks() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    pipeline = RecordingPipeline()

    result = process_import_task(
        store,
        unit_of_work,
        pipeline,
        ImportRuntimeConfig(
            storage_root=Path("/tmp"),
            audiobook_max_file_bytes=1,
        ),
        _task(),
        now=123,
    )

    assert result.work_id == "work-1"
    assert store.calls == ["library", "library", "download"]
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0
    assert pipeline.completed == 1


def test_process_import_rejects_task_without_scanner_topology_target() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    pipeline = RecordingPipeline()
    task = ImportTaskDTO(
        id="task-retry",
        source_path="/tmp/book.epub",
        origin="MANUAL",
        status="PARSING",
        library_id="folder-1",
        work_id="previous-result-work",
    )

    with pytest.raises(ImportExecutionError) as error:
        process_import_task(
            store,
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"), audiobook_max_file_bytes=1
            ),
            task,
            now=123,
        )

    assert error.value.code == "TOPOLOGY_TARGET_REQUIRED"
    assert error.value.retryable is False
    assert pipeline.imports == 0
    assert unit_of_work.rollbacks == 1


def test_scanner_task_forwards_its_bound_directory_topology() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    pipeline = RecordingPipeline()
    task = ImportTaskDTO(
        id="task-scan",
        source_path="/tmp/book.epub",
        origin="WATCH",
        status="PARSING",
        library_id="folder-1",
        work_id="topology-work",
        volume_id="topology-volume",
    )

    process_import_task(
        store,
        unit_of_work,
        pipeline,
        ImportRuntimeConfig(storage_root=Path("/tmp"), audiobook_max_file_bytes=1),
        task,
        now=123,
    )

    assert pipeline.options is not None
    assert pipeline.options.topology_work_id == "topology-work"
    assert pipeline.options.topology_volume_id == "topology-volume"


@pytest.mark.parametrize("failure", ["download"])
def test_process_import_rolls_back_all_final_writes_when_post_hook_fails(
    failure: str,
) -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore(fail_at=failure)
    pipeline = RecordingPipeline()

    with pytest.raises(RuntimeError, match="synchronization failed"):
        process_import_task(
            store,
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1
    assert pipeline.completed == 0


def test_process_import_stops_before_pipeline_when_library_was_deleted() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    store.library_available = False
    pipeline = RecordingPipeline()

    with pytest.raises(LibraryDeletedDuringImportError):
        process_import_task(
            store,
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert pipeline.imports == 0
    assert unit_of_work.rollbacks == 1
    assert pipeline.completed == 0


def test_process_import_stops_when_library_id_is_missing() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    pipeline = RecordingPipeline()
    task = ImportTaskDTO(
        id="task-unscoped",
        source_path="/tmp/book.epub",
        origin="MANUAL",
        status="PARSING",
        library_id=None,
    )

    with pytest.raises(LibraryDeletedDuringImportError):
        process_import_task(
            store,
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                audiobook_max_file_bytes=1,
            ),
            task,
            now=123,
        )

    assert pipeline.imports == 0
    assert store.calls == []
    assert unit_of_work.rollbacks == 1
    assert pipeline.completed == 0


def test_process_import_rolls_back_when_library_is_deleted_during_pipeline() -> None:
    unit_of_work = RecordingUnitOfWork()
    store = RecordingStore()
    pipeline = RecordingPipeline(
        after_import=lambda: setattr(store, "library_available", False)
    )

    with pytest.raises(LibraryDeletedDuringImportError):
        process_import_task(
            store,
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert store.calls == ["library", "library"]
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1
    assert pipeline.completed == 0


class FailureRecordingStore:
    def __init__(self) -> None:
        self.failure: dict[str, object] | None = None
        self.event_staged = False
        self.library_available = False

    def library_exists(self, library_id: str) -> bool:
        return self.library_available

    def fail_claimed(
        self,
        task: ImportTaskDTO,
        *,
        error_code: str,
        error_summary: str,
        message: str,
        retryable: bool,
        now: int,
    ) -> bool:
        self.failure = {
            "error_code": error_code,
            "error_summary": error_summary,
            "message": message,
            "retryable": retryable,
        }
        return True

    def stage_failure_event(
        self,
        task: ImportTaskDTO,
        *,
        error_summary: str,
        now: int,
    ) -> None:
        self.event_staged = True


class ExistingSourceProbe:
    def exists(self, path: Path) -> bool:
        return True


def test_fail_claimed_import_is_terminal_when_library_was_deleted() -> None:
    store = FailureRecordingStore()
    unit_of_work = RecordingUnitOfWork()

    failed = fail_claimed_import_task(
        store,
        unit_of_work,
        _task(),
        LibraryDeletedDuringImportError(),
        now=123,
        source_probe=ExistingSourceProbe(),
    )

    assert failed is True
    assert store.failure == {
        "error_code": "LIBRARY_NOT_FOUND",
        "error_summary": "书库已在导入期间被删除",
        "message": "书库已被删除，本次导入任务已结束",
        "retryable": False,
    }
    assert store.event_staged is True
    assert unit_of_work.commits == 1


def test_fail_claimed_import_is_terminal_when_library_id_is_missing() -> None:
    store = FailureRecordingStore()
    store.library_available = True
    unit_of_work = RecordingUnitOfWork()
    task = ImportTaskDTO(
        id="task-unscoped",
        source_path="/tmp/book.epub",
        origin="MANUAL",
        status="PARSING",
        library_id=None,
    )

    failed = fail_claimed_import_task(
        store,
        unit_of_work,
        task,
        LibraryDeletedDuringImportError(),
        now=123,
        source_probe=ExistingSourceProbe(),
    )

    assert failed is True
    assert store.failure == {
        "error_code": "LIBRARY_NOT_FOUND",
        "error_summary": "书库已在导入期间被删除",
        "message": "书库已被删除，本次导入任务已结束",
        "retryable": False,
    }
    assert store.event_staged is True
    assert unit_of_work.commits == 1


def test_fail_claimed_import_preserves_named_execution_failure() -> None:
    store = FailureRecordingStore()
    store.library_available = True
    unit_of_work = RecordingUnitOfWork()

    failed = fail_claimed_import_task(
        store,
        unit_of_work,
        _task(),
        ImportExecutionError(
            "CONVERTER_UNAVAILABLE",
            "电子书转换服务不可用",
            retryable=True,
        ),
        now=123,
        source_probe=ExistingSourceProbe(),
    )

    assert failed is True
    assert store.failure == {
        "error_code": "CONVERTER_UNAVAILABLE",
        "error_summary": "电子书转换服务不可用",
        "message": "导入处理失败，任务已结束",
        "retryable": True,
    }
    assert store.event_staged is True
    assert unit_of_work.commits == 1


def test_process_import_does_not_roll_back_published_files_when_final_commit_fails() -> (
    None
):
    unit_of_work = RecordingUnitOfWork(fail_commit=True)
    pipeline = RecordingPipeline()

    with pytest.raises(RuntimeError, match="commit failed"):
        process_import_task(
            RecordingStore(),
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 1
    assert pipeline.completed == 1
