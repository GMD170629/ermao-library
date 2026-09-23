"""Unit coverage: minimize ADR 0018 queue ownership and containment paths."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImport,
    ContinueImportTask,
)
from app.modules.imports.application.readable_resource.ports import (
    BookImportTaskRecord,
    FileParseResult,
    LibraryImportTaskRecord,
)
from app.modules.imports.application.readable_resource.process_book_resources import (
    BookResourceBatchResult,
    ProcessBookResources,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
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
            missing_entry_policy=self._base.missing_entry_policy,
        )

    def next_queued(self) -> LibraryImportTaskRecord | None:
        return self._snapshot()

    def prepare_book_identifications(self) -> tuple[()]:
        return ()

    def enqueue_book_identifications(self, prepared: tuple[()]) -> int:
        raise AssertionError("no pending books in this queue fixture")

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

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        del finished_at
        return 0

    def requeue_failed_task(self, task_id: str) -> tuple[LibraryImportTaskRecord, bool]:
        if task_id != self._base.id:
            raise LookupError(task_id)
        if self._state != "FAILED":
            return self._snapshot(), False
        self._state = "QUEUED"
        self._error_summary = None
        return self._snapshot(), True


class FakeBookQueue:
    def __init__(self, legacy_queue: FakeQueue) -> None:
        self._legacy_queue = legacy_queue
        self.cancelled = False
        self.failures: list[tuple[str, str]] = []
        self.finished = 0
        self._task = BookImportTaskRecord(
            id="task-1",
            book_id="book-1",
            library_id="lib-1",
            source_node_id="node-1",
            state="RUNNING",
            phase="RESOURCES",
            request_version=1,
            execution_version=1,
            work=BookWorkState(active=BookWork(resource_ids=("res-1",))),
            resource_cursor=None,
            retry_count=0,
            next_attempt_at=FixedClock().now(),
            error_summary=None,
        )

    def claim_next_book(self, *, started_at: datetime) -> BookImportTaskRecord | None:
        del started_at
        return None if self.cancelled else self._task

    def get_book_task(self, task_id: str) -> BookImportTaskRecord | None:
        return self._task if task_id == self._task.id and not self.cancelled else None

    def book_run_is_current(
        self, task_id: str, *, execution_version: int, **kwargs: object
    ) -> bool:
        del kwargs
        return (
            not self.cancelled
            and task_id == self._task.id
            and execution_version == self._task.execution_version
        )

    def advance_book_resource_cursor(self, **kwargs: object) -> bool:
        del kwargs
        return True

    def advance_book_phase(self, **kwargs: object) -> bool:
        del kwargs
        return True

    def yield_book_run(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def finish_book_run(
        self, *args: object, **kwargs: object
    ) -> BookImportTaskRecord | None:
        del args, kwargs
        if self.cancelled:
            return None
        self.finished += 1
        self._legacy_queue._state = "SUCCEEDED"
        return self._task

    def fail_book_run(
        self,
        task_id: str,
        *,
        execution_version: int,
        error_summary: str,
        retryable: bool,
        failed_at: datetime,
        partial_failure: bool = False,
    ) -> BookImportTaskRecord | None:
        del execution_version, retryable, failed_at, partial_failure
        self.failures.append((task_id, error_summary))
        self._legacy_queue._state = "FAILED"
        self._legacy_queue._error_summary = error_summary
        return self._task

    def cancel(self) -> None:
        self.cancelled = True
        self._legacy_queue.cancel()


class FakeBookResources:
    def __init__(
        self,
        *,
        outcome: str | None = None,
        error: Exception | None = None,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._outcome = outcome
        self._error = error
        self._on_execute = on_execute

    def execute(
        self, task: BookImportTaskRecord, *, max_resources: int
    ) -> BookResourceBatchResult:
        assert task.id == "task-1"
        assert max_resources == 128
        if self._on_execute is not None:
            self._on_execute()
        if self._error is not None:
            raise self._error
        assert self._outcome is not None
        return BookResourceBatchResult(
            self._outcome,
            "PARSE_FAILED" if self._outcome == "failed" else None,
        )


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
    def reset_inspection_cache(self) -> None:
        pass

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
    def observe_readable_file(self, path: Path) -> None:
        return None

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
        self.adapter_version = "1"
        self.format = "EPUB"


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
    def execute_library(
        self,
        library_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
        scan_scopes: object = None,
    ) -> None:
        del task_id, missing_entry_policy
        raise AssertionError(library_id)

    def execute_source(
        self,
        source_node_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
    ) -> None:
        del task_id, missing_entry_policy
        raise AssertionError(source_node_id)


class CancelDuringScan:
    def __init__(self, queue: FakeQueue) -> None:
        self._queue = queue
        self.received_policy: MissingEntryPolicy | None = None

    def execute_library(
        self,
        library_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
        scan_scopes: object = None,
    ) -> None:
        assert library_id == "lib-1"
        assert task_id == "task-1"
        self.received_policy = missing_entry_policy
        self._queue.cancel()

    def execute_source(
        self,
        source_node_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
    ) -> None:
        del source_node_id, task_id, missing_entry_policy
        raise AssertionError("unexpected source scan")


def _import_task() -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="IMPORT_RESOURCE",
        library_id="lib-1",
        state="QUEUED",
        resource_id="res-1",
        source_node_id="node-1",
        role=AssetRole.PRIMARY,
        error_summary=None,
    )


def _scan_task(
    missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
) -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="SCAN_LIBRARY",
        library_id="lib-1",
        state="QUEUED",
        resource_id=None,
        source_node_id=None,
        role=None,
        error_summary=None,
        missing_entry_policy=missing_entry_policy,
    )


def _book_task() -> LibraryImportTaskRecord:
    return LibraryImportTaskRecord(
        id="task-1",
        kind="IMPORT_BOOK",
        library_id="lib-1",
        state="RUNNING",
        resource_id=None,
        source_node_id="node-1",
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


def _book_worker(
    *,
    queue: FakeQueue,
    book_queue: FakeBookQueue,
    resources: FakeBookResources,
) -> ReadableResourceWorkerProcessor:
    return ReadableResourceWorkerProcessor(
        queue=queue,
        scan=cast(ScanLibrarySourceTree, UnusedScan()),
        process_import=_process(adapters=ParseFailAdapters(), queue=queue),
        process_book_resources=cast(ProcessBookResources, resources),
        book_queue=book_queue,
        uow=RecordingUoW(),
        clock=FixedClock(),
    )


def test_continue_exact_failed_task_preserves_missing_entry_policy() -> None:
    task = LibraryImportTaskRecord(
        id="task-1",
        kind="CONTINUE_SOURCE",
        library_id="lib-1",
        state="FAILED",
        resource_id=None,
        source_node_id="node-1",
        role=None,
        error_summary="SOURCE_SCAN_START_UNAVAILABLE",
        missing_entry_policy=MissingEntryPolicy.PRESERVE,
    )
    queue = FakeQueue(task)
    result = ContinueImport(
        source_nodes=FakeSourceNodes(),
        queue=queue,
        uow=RecordingUoW(),
        log=FakeLog(),
    ).execute(ContinueImportTask(task.id))

    assert result.requeued_failed == 1
    assert result.enqueued_scan is True
    assert result.task_id == task.id
    retried = queue.get_task(task.id)
    assert retried is not None
    assert retried.missing_entry_policy is MissingEntryPolicy.PRESERVE


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


def test_book_worker_containment_logs_without_worker_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = FakeQueue(_book_task())
    book_queue = FakeBookQueue(queue)
    worker = _book_worker(
        queue=queue,
        book_queue=book_queue,
        resources=FakeBookResources(error=RuntimeError("boom")),
    )
    with caplog.at_level(logging.ERROR, logger="ermao.readable_resource_pipeline"):
        assert worker.process_once() == "error"
    assert book_queue.failures == [("task-1", "WORKER_ERROR")]
    assert all(summary != "UNHANDLED_ERROR" for _, summary in book_queue.failures)
    records = [
        record
        for record in caplog.records
        if record.getMessage().startswith(
            "readable_resource.worker.containment_failure"
        )
    ]
    assert len(records) == 1
    assert getattr(records[0], "task_id", None) == "task-1"
    assert getattr(records[0], "task_kind", None) == "IMPORT_BOOK"
    assert getattr(records[0], "book_id", None) == "book-1"
    assert getattr(records[0], "stage", None) == "worker"
    assert getattr(records[0], "outcome", None) == "error"
    assert not hasattr(records[0], "worker_id")


def test_modeled_book_resource_failure_is_not_rewritten_as_worker_error() -> None:
    queue = FakeQueue(_book_task())
    book_queue = FakeBookQueue(queue)
    worker = _book_worker(
        queue=queue,
        book_queue=book_queue,
        resources=FakeBookResources(outcome="failed"),
    )
    assert worker.process_once() == "failed"
    assert book_queue.failures == [("task-1", "PARSE_FAILED")]


def test_book_work_cancelled_during_resource_processing_does_not_commit_failure() -> None:
    queue = FakeQueue(_book_task())
    book_queue = FakeBookQueue(queue)
    worker = _book_worker(
        queue=queue,
        book_queue=book_queue,
        resources=FakeBookResources(
            outcome="cancelled", on_execute=book_queue.cancel
        ),
    )

    assert worker.process_once() == "cancelled"
    assert book_queue.failures == []
    assert book_queue.finished == 0


def test_scan_task_deleted_while_running_is_not_acknowledged() -> None:
    queue = FakeQueue(_scan_task(MissingEntryPolicy.PRUNE_MISSING))
    scan = CancelDuringScan(queue)
    worker = ReadableResourceWorkerProcessor(
        queue=queue,
        scan=cast(ScanLibrarySourceTree, scan),
        process_import=_process(adapters=ParseFailAdapters(), queue=queue),
        uow=RecordingUoW(),
        clock=FixedClock(),
    )

    assert worker.process_once() == "cancelled"
    assert queue.failed == []
    assert scan.received_policy is MissingEntryPolicy.PRUNE_MISSING
