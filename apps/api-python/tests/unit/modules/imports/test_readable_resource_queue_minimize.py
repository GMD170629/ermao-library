"""Unit coverage: minimize ADR 0018 queue ownership and containment paths."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImport,
)
from app.modules.imports.application.readable_resource.ports import (
    FileParseResult,
    LibraryImportTaskRecord,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)
from app.modules.library.application.source_tree_ports import (
    LibrarySourceTreeConfig,
    SourceNodeRecord,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


class RecordingUoW:
    def __init__(self) -> None:
        self.in_transaction = False
        self.rollback_count = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    def release_before_io(self) -> None:
        assert not self.in_transaction

    def rollback(self) -> None:
        self.rollback_count += 1
        self.in_transaction = False


class FixedClock:
    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC)


class FakeLog:
    def emit(self, event: str, **kwargs: object) -> None:
        del event, kwargs


class FakeSidecar:
    def schedule_after_commit(self, resource_id: str) -> None:
        del resource_id


class FakeQueue:
    def __init__(self, task: LibraryImportTaskRecord) -> None:
        self._base = task
        self._state = task.state
        self._error_summary = task.error_summary
        self.cancelled = False
        self.failed: list[tuple[str, str]] = []

    def _snapshot(self) -> LibraryImportTaskRecord:
        return LibraryImportTaskRecord(
            id=self._base.id,
            kind=self._base.kind,
            library_id=self._base.library_id,
            state=self._state,
            resource_id=self._base.resource_id,
            source_node_id=self._base.source_node_id,
            role=self._base.role,
            error_summary=self._error_summary,
        )

    def next_queued(self) -> LibraryImportTaskRecord | None:
        return self._snapshot()

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        if task_id != self._base.id or self.cancelled:
            return None
        return self._snapshot()

    def cancel(self) -> None:
        self.cancelled = True

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        del started_at
        assert task_id == self._base.id
        self._state = "RUNNING"

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        del task_id, finished_at
        raise AssertionError("unexpected success")

    def mark_failed(
        self, task_id: str, *, error_summary: str, finished_at: datetime
    ) -> None:
        del finished_at
        self.failed.append((task_id, error_summary))
        self._state = "FAILED"
        self._error_summary = error_summary

    def enqueue(self, **kwargs: object) -> LibraryImportTaskRecord:
        raise NotImplementedError

    def ensure_import_asset_task(self, **kwargs: object) -> None:
        return None

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        del finished_at
        return 0

    def requeue_failed_for_library(self, library_id: str) -> int:
        del library_id
        return 0

    def requeue_failed_for_source(self, source_node_id: str) -> int:
        del source_node_id
        return 0

    def has_active_kind(self, **kwargs: object) -> bool:
        return False


class BoomAdapters:
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **_kwargs: object,
    ) -> FileParseResult:
        del absolute_path, adapter, role
        raise RuntimeError("boom")


class ParseFailAdapters:
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **_kwargs: object,
    ) -> FileParseResult:
        del absolute_path
        return FileParseResult(
            ok=False,
            adapter=adapter,
            resource_title=None,
            asset=None,
            error_code="PARSE_FAILED",
            error_summary="PARSE_FAILED",
        )


class CancelDuringParseAdapters(ParseFailAdapters):
    def __init__(self, queue: FakeQueue) -> None:
        self._queue = queue

    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        **kwargs: object,
    ) -> FileParseResult:
        result = super().parse_file(
            absolute_path=absolute_path,
            adapter=adapter,
            role=role,
            **kwargs,
        )
        self._queue.cancel()
        return result


class FakeLibraries:
    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        return LibrarySourceTreeConfig(
            library_id=library_id,
            root_path=Path("/tmp/lib"),
            organization_mode=TargetLibraryOrganizationMode.FLAT,
            ignore_hidden=True,
            ignore_patterns=None,
            global_ignore_patterns="",
            probe_sample_limit=100,
            probe_max_entries=10_000,
            probe_max_depth=8,
            probe_time_budget_ms=5_000,
        )

    def source_node_count(self, library_id: str) -> int:
        del library_id
        return 0

    def update_organization_mode(self, library_id: str, mode: object) -> None:
        raise NotImplementedError

    def update_root_path(self, library_id: str, root_path: Path) -> None:
        raise NotImplementedError

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool:
        del root_path, exclude_library_id
        return False


class FakeFilesystem:
    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        return root / relative_path

    def iter_directory_entries(self, absolute_directory: Path) -> Iterator[object]:
        del absolute_directory
        yield from ()

    def probe_directory(self, **kwargs: object) -> object:
        raise NotImplementedError

    def path_is_readable_directory(self, path: Path) -> bool:
        del path
        return True


class FakeSourceNodes:
    def get(self, source_node_id: str) -> SourceNodeRecord:
        return SourceNodeRecord(
            id=source_node_id,
            library_id="lib-1",
            parent_id=None,
            relative_path="book.epub",
            path_key="key",
            name="book.epub",
            physical_kind=SourceNodePhysicalKind.REGULAR_FILE,
            observed_size_bytes=1,
            observed_mtime_ns=1,
            observed_at=datetime(2024, 1, 1, tzinfo=UTC),
        )

    def get_by_path_key(self, library_id: str, path_key: str) -> None:
        del library_id, path_key

    def insert_if_absent(self, **kwargs: object) -> None:
        raise NotImplementedError

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]:
        return (source_node_id,)

    def delete_subtree(self, source_node_id: str) -> None:
        raise NotImplementedError

    def get_interpretation(self, source_node_id: str) -> None:
        del source_node_id

    def upsert_interpretation(self, **kwargs: object) -> None:
        return None


class FakeResource:
    def __init__(self) -> None:
        self.id = "res-1"
        self.library_id = "lib-1"
        self.source_node_id = "node-1"
        self.adapter_id = "epub"


class FakeBooks:
    def get_resource(self, resource_id: str) -> FakeResource:
        del resource_id
        return FakeResource()

    def get_resource_by_source_node(self, source_node_id: str) -> None:
        del source_node_id

    def get_book_id_for_source_node(self, source_node_id: str) -> None:
        del source_node_id

    def ensure_book(self, **kwargs: object) -> str:
        return "book-1"

    def create_pending_resource(self, **kwargs: object) -> FakeResource:
        return FakeResource()

    def set_enablement(self, *args: object, **kwargs: object) -> None:
        return None

    def mark_resource_ready(self, **kwargs: object) -> None:
        return None

    def mark_resource_failed(self, resource_id: str) -> None:
        del resource_id

    def upsert_asset(self, **kwargs: object) -> str:
        del kwargs
        return "asset-1"

    def count_ready_assets(self, resource_id: str) -> int:
        del resource_id
        return 0

    def find_outermost_directory_resource(
        self, library_id: str, relative_path: str
    ) -> None:
        del library_id, relative_path

    def delete_library_overlay_rows(self, library_id: str) -> None:
        del library_id

    def delete_assets_for_source_nodes(
        self, source_node_ids: object
    ) -> tuple[str, ...]:
        del source_node_ids
        return ()

    def reevaluate_ready_after_asset_loss(self, resource_ids: object) -> None:
        del resource_ids


class UnusedScan:
    def execute_library(self, library_id: str) -> None:
        raise AssertionError(library_id)

    def execute_source(self, source_node_id: str) -> None:
        raise AssertionError(source_node_id)


class CancelDuringScan:
    def __init__(self, queue: FakeQueue) -> None:
        self._queue = queue

    def execute_library(self, library_id: str, *, task_id: str | None = None) -> None:
        assert library_id == "lib-1"
        assert task_id == "task-1"
        self._queue.cancel()

    def execute_source(
        self, source_node_id: str, *, task_id: str | None = None
    ) -> None:
        del source_node_id, task_id
        raise AssertionError("unexpected source scan")


def _import_task() -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="IMPORT_ASSET",
        library_id="lib-1",
        state="QUEUED",
        resource_id="res-1",
        source_node_id="node-1",
        role=AssetRole.PRIMARY,
        error_summary=None,
    )


def _scan_task() -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="SCAN_LIBRARY",
        library_id="lib-1",
        state="QUEUED",
        resource_id=None,
        source_node_id=None,
        role=None,
        error_summary=None,
    )


def _process(
    *,
    adapters: BoomAdapters | ParseFailAdapters,
    queue: FakeQueue,
) -> ProcessReadableResourceImportTask:
    return ProcessReadableResourceImportTask(
        libraries=FakeLibraries(),
        filesystem=FakeFilesystem(),
        source_nodes=FakeSourceNodes(),
        books_resources=FakeBooks(),
        adapters=adapters,
        queue=queue,
        uow=RecordingUoW(),
        clock=FixedClock(),
        log=FakeLog(),
        sidecar=FakeSidecar(),
    )


def _worker(
    *,
    adapters: BoomAdapters | ParseFailAdapters,
    queue: FakeQueue,
) -> ReadableResourceWorkerProcessor:
    return ReadableResourceWorkerProcessor(
        queue=queue,
        scan=cast(ScanLibrarySourceTree, UnusedScan()),
        process_import=_process(adapters=adapters, queue=queue),
        uow=RecordingUoW(),
        clock=FixedClock(),
    )


def test_continue_import_constructs_without_clock() -> None:
    ContinueImport(
        source_nodes=FakeSourceNodes(),
        queue=FakeQueue(_import_task()),
        uow=RecordingUoW(),
        log=FakeLog(),
    )


def test_worker_exposes_explicit_process_loop_recovery() -> None:
    queue = FakeQueue(_import_task())
    unit_of_work = RecordingUoW()
    worker = ReadableResourceWorkerProcessor(
        queue=queue,
        scan=cast(ScanLibrarySourceTree, UnusedScan()),
        process_import=_process(adapters=BoomAdapters(), queue=queue),
        uow=unit_of_work,
        clock=FixedClock(),
    )

    worker.recover_after_loop_failure()

    assert unit_of_work.rollback_count == 1


def test_worker_containment_logs_without_worker_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = FakeQueue(_import_task())
    worker = _worker(adapters=BoomAdapters(), queue=queue)
    with caplog.at_level(logging.ERROR, logger="ermao.readable_resource_pipeline"):
        assert worker.process_once() == "error"
    assert queue.failed == [("task-1", "WORKER_ERROR")]
    assert all(summary != "UNHANDLED_ERROR" for _, summary in queue.failed)
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "readable_resource.worker.containment_failure"
    ]
    assert len(records) == 1
    assert getattr(records[0], "task_id", None) == "task-1"
    assert getattr(records[0], "stage", None) == "worker"
    assert getattr(records[0], "outcome", None) == "error"
    assert not hasattr(records[0], "worker_id")


def test_modeled_parse_failure_is_not_rewritten_as_worker_error() -> None:
    queue = FakeQueue(_import_task())
    worker = _worker(adapters=ParseFailAdapters(), queue=queue)
    assert worker.process_once() == "failed"
    assert queue.failed == [("task-1", "PARSE_FAILED")]


def test_import_task_cancelled_during_parse_does_not_commit_failure() -> None:
    queue = FakeQueue(_import_task())
    worker = _worker(adapters=CancelDuringParseAdapters(queue), queue=queue)

    assert worker.process_once() == "cancelled"
    assert queue.failed == []


def test_scan_task_deleted_while_running_is_not_acknowledged() -> None:
    queue = FakeQueue(_scan_task())
    worker = ReadableResourceWorkerProcessor(
        queue=queue,
        scan=cast(ScanLibrarySourceTree, CancelDuringScan(queue)),
        process_import=_process(adapters=ParseFailAdapters(), queue=queue),
        uow=RecordingUoW(),
        clock=FixedClock(),
    )

    assert worker.process_once() == "cancelled"
    assert queue.failed == []
