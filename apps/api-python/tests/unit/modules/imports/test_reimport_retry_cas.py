from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from app.modules.imports.application.readable_resource.ports import (
    LibraryImportTaskRecord,
)
from app.modules.imports.application.readable_resource.reimport import (
    RetryReadableResourceImport,
)
from app.modules.imports.domain.import_run_policies import (
    ImportRunKind,
    ImportRunState,
    LibraryImportTaskState,
)
from app.modules.library.application.source_tree_ports import ReadableResourceRecord
from app.modules.library.domain.readable_resource_states import (
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
)


class SimpleUoW:
    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def release_before_io(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class FakeBooks:
    def __init__(self, resource: ReadableResourceRecord, *, cas_ok: bool) -> None:
        self.resource = resource
        self.cas_ok = cas_ok
        self.cas_calls = 0

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None:
        return self.resource if self.resource.id == resource_id else None

    def cas_set_active_import_run(
        self,
        resource_id: str,
        *,
        expected_active_run_id: str | None,
        new_active_run_id: str | None,
    ) -> bool:
        self.cas_calls += 1
        return self.cas_ok


class FakeImportRuns:
    def __init__(self) -> None:
        self.created_runs: list[tuple[str, ImportRunKind]] = []
        self.run_states: list[tuple[str, ImportRunState, str | None]] = []
        self.tasks: list[str] = []
        self._seq = 0

    def create_run(
        self,
        *,
        library_id: str,
        kind: ImportRunKind,
        source_node_id: str,
        resource_id: str | None,
        adapter_id: str | None,
        adapter_version: str | None,
    ) -> str:
        self._seq += 1
        run_id = f"run-{self._seq}"
        self.created_runs.append((run_id, kind))
        return run_id

    def set_run_state(
        self,
        run_id: str,
        state: ImportRunState,
        *,
        error_summary: str | None = None,
        published_at: object | None = None,
    ) -> None:
        self.run_states.append((run_id, state, error_summary))

    def create_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        owner_import_run_id: str | None,
        role: AssetRole,
    ) -> LibraryImportTaskRecord:
        task_id = f"task-{len(self.tasks) + 1}"
        self.tasks.append(task_id)
        return LibraryImportTaskRecord(
            id=task_id,
            library_id=library_id,
            state=LibraryImportTaskState.QUEUED,
            resource_id=resource_id,
            source_node_id=source_node_id,
            owner_import_run_id=owner_import_run_id,
            role=role,
            attempt_count=0,
        )


class FakeSourceNodes:
    def get(self, source_node_id: str) -> None:
        return None


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue_library_import_task(self, task_id: str) -> None:
        self.enqueued.append(task_id)

    def queued_item_count(self) -> int:
        return len(self.enqueued)

    def enqueue_library_scan(self, library_id: str) -> None:
        return None

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> None:
        return None

    def complete(self, claim: object) -> bool:
        return True

    def heartbeat(self, claim: object) -> bool:
        return True

    def is_claim_valid(self, claim: object) -> bool:
        return True


class FakeLog:
    def emit(self, event: str, **kwargs: object) -> None:
        return None


def test_retry_cas_failure_marks_run_failed_not_running_orphan() -> None:
    resource = ReadableResourceRecord(
        id="res-1",
        library_id="lib-1",
        book_id="book-1",
        source_node_id="node-1",
        adapter_id="epub",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        enablement_state=ResourceEnablementState.ENABLED,
        import_state=ResourceImportState.FAILED,
        published_run_id=None,
        active_import_run_id="busy-run",
    )
    books = FakeBooks(resource, cas_ok=False)
    runs = FakeImportRuns()
    queue = FakeQueue()
    usecase = RetryReadableResourceImport(
        books_resources=books,
        import_runs=runs,
        source_nodes=FakeSourceNodes(),
        queue=queue,
        uow=SimpleUoW(),
        log=FakeLog(),
    )
    result = usecase.execute("res-1")
    assert result.ok is False
    assert result.code == "ACTIVE_RUN_BUSY"
    assert result.run_id == "run-1"
    assert books.cas_calls == 1
    assert runs.run_states == [
        ("run-1", ImportRunState.FAILED, "active_run_cas_failed")
    ]
    assert queue.enqueued == []
    assert runs.tasks == []
    # Must not leave a RUNNING orphan: only FAILED was recorded after create.
    assert all(state is ImportRunState.FAILED for _, state, _ in runs.run_states)


def test_retry_cas_success_enqueues_owned_task() -> None:
    resource = ReadableResourceRecord(
        id="res-1",
        library_id="lib-1",
        book_id="book-1",
        source_node_id="node-1",
        adapter_id="epub",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        enablement_state=ResourceEnablementState.ENABLED,
        import_state=ResourceImportState.FAILED,
        published_run_id=None,
        active_import_run_id=None,
    )
    books = FakeBooks(resource, cas_ok=True)
    runs = FakeImportRuns()
    queue = FakeQueue()
    usecase = RetryReadableResourceImport(
        books_resources=books,
        import_runs=runs,
        source_nodes=FakeSourceNodes(),
        queue=queue,
        uow=SimpleUoW(),
        log=FakeLog(),
    )
    result = usecase.execute("res-1")
    assert result.ok is True
    assert result.run_id == "run-1"
    assert runs.run_states == []
    assert queue.enqueued == ["task-1"]
