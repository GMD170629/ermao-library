from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.modules.imports.application.dto import (
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
)
from app.modules.imports.application.process import process_import_task


@dataclass
class RecordingUnitOfWork:
    commits: int = 0
    rollbacks: int = 0
    fail_commit: bool = False

    def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rollbacks += 1


class RecordingStore:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []

    def link_work_to_monitor_shelf(
        self,
        monitor_folder_id: str | None,
        work_id: str,
        *,
        created_at: int,
    ) -> None:
        self.calls.append("shelf")
        if self.fail_at == "shelf":
            raise RuntimeError("shelf synchronization failed")

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
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.finalized = 0
        self.rolled_back = 0

    def import_managed_book(
        self,
        settings: object,
        options: object,
    ) -> ImportResult:
        if self.fail:
            raise RuntimeError("final import synchronization failed")
        return ImportResult(
            book_id="work-1",
            work_id="work-1",
            edition_id="edition-1",
            volume_id=None,
            title="测试书",
            type="EPUB",
            format="EPUB",
            total_units=1,
            import_status="completed",
            duplicate=False,
            merged=False,
            merge_reason="new",
        )

    def finalize_publications(self) -> None:
        self.finalized += 1

    def rollback_publications(self) -> None:
        self.rolled_back += 1


def _task() -> ImportTaskDTO:
    return ImportTaskDTO(
        id="task-1",
        source_path="/tmp/book.epub",
        origin="MANUAL",
        status="PARSING",
        monitor_folder_id="folder-1",
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
            monitor_root=None,
            audiobook_max_file_bytes=1,
        ),
        _task(),
        now=123,
    )

    assert result.work_id == "work-1"
    assert store.calls == ["shelf", "download"]
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0
    assert pipeline.finalized == 1
    assert pipeline.rolled_back == 0


@pytest.mark.parametrize("failure", ["shelf", "download"])
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
                monitor_root=None,
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1
    assert pipeline.rolled_back == 1


def test_process_import_rolls_back_publications_when_final_commit_fails() -> None:
    unit_of_work = RecordingUnitOfWork(fail_commit=True)
    pipeline = RecordingPipeline()

    with pytest.raises(RuntimeError, match="commit failed"):
        process_import_task(
            RecordingStore(),
            unit_of_work,
            pipeline,
            ImportRuntimeConfig(
                storage_root=Path("/tmp"),
                monitor_root=None,
                audiobook_max_file_bytes=1,
            ),
            _task(),
            now=123,
        )

    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 1
    assert pipeline.finalized == 0
    assert pipeline.rolled_back == 1
