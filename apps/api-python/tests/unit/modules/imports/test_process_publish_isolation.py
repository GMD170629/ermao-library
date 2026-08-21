from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    AssetCandidateRecord,
    AssetTechnicalMetadata,
    ClaimedWork,
    FileParseResult,
    LibraryImportTaskRecord,
    ParsedAssetPayload,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.domain.import_run_policies import (
    ImportRunState,
    LibraryImportTaskState,
)
from app.modules.imports.domain.resource_adapters import ADAPTER_SPECS, ResourceAdapterId
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    LibrarySourceTreeConfig,
    ReadableResourceRecord,
    SourceNodeRecord,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
)
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind


def _now() -> datetime:
    return datetime(2024, 6, 1, tzinfo=timezone.utc)


def _epub_adapter():
    return next(s for s in ADAPTER_SPECS if s.adapter_id is ResourceAdapterId.EPUB)


class SimpleUoW:
    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def release_before_io(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class FakeLibraries:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        return LibrarySourceTreeConfig(
            library_id=library_id,
            root_path=self._root,
            organization_mode=TargetLibraryOrganizationMode.FLAT,
            ignore_hidden=True,
            ignore_patterns=None,
            global_ignore_patterns="",
            min_file_size_bytes=0,
            queue_high_water=1000,
            probe_sample_limit=100,
            probe_max_entries=10_000,
            probe_max_depth=8,
            probe_time_budget_ms=5_000,
        )


class FakeFilesystem:
    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        return root / relative_path

    def iter_directory_entries(self, absolute_directory: Path):
        yield from ()

    def probe_directory(self, **kwargs: object):
        raise NotImplementedError

    def path_is_readable_directory(self, path: Path) -> bool:
        return True


class FakeSourceNodes:
    def __init__(self, node: SourceNodeRecord) -> None:
        self._node = node

    def get(self, source_node_id: str) -> SourceNodeRecord | None:
        return self._node if self._node.id == source_node_id else None

    def get_by_path_key(self, library_id: str, path_key: str) -> SourceNodeRecord | None:
        return None


class TrackingBooks:
    def __init__(self, resource: ReadableResourceRecord) -> None:
        self.resource = resource
        self.publish_calls: list[str] = []
        self.upsert_asset_calls: list[str] = []
        self.events: list[str] = []

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None:
        return self.resource if self.resource.id == resource_id else None

    def publish_resource(
        self,
        *,
        resource_id: str,
        published_run_id: str,
        adapter: AdapterIdentity,
        title: str,
    ) -> None:
        self.publish_calls.append(published_run_id)
        self.events.append(f"publish:{published_run_id}")
        self.resource = replace(
            self.resource,
            import_state=ResourceImportState.READY,
            published_run_id=published_run_id,
            active_import_run_id=None,
        )

    def upsert_asset(self, *, published_run_id: str, **kwargs: object) -> str:
        self.upsert_asset_calls.append(published_run_id)
        self.events.append(f"upsert_asset:{published_run_id}")
        return "asset-1"

    def count_ready_assets_for_published_run(
        self, resource_id: str, published_run_id: str
    ) -> int:
        return len(self.upsert_asset_calls)

    def clear_active_import_run(self, resource_id: str) -> None:
        self.resource = replace(self.resource, active_import_run_id=None)
        self.events.append("clear_active")

    def mark_resource_failed(self, resource_id: str) -> None:
        self.resource = replace(self.resource, import_state=ResourceImportState.FAILED)

    def cleanup_stale_assets(self, resource_id: str, published_run_id: str) -> None:
        self.events.append(f"cleanup:{published_run_id}")

    def cas_set_active_import_run(self, *args: object, **kwargs: object) -> bool:
        return True


class TrackingImportRuns:
    def __init__(self, task: LibraryImportTaskRecord) -> None:
        self.task = task
        self.asset_candidates: list[AssetCandidateRecord] = []
        self.task_states: list[LibraryImportTaskState] = []
        self.run_states: list[ImportRunState] = []
        self.events: list[str] = []
        self.incomplete = 0
        self.failed = 0

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        return self.task if self.task.id == task_id else None

    def mark_task_state(
        self,
        task_id: str,
        state: LibraryImportTaskState,
        *,
        error_summary: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        self.task_states.append(state)
        self.events.append(f"task:{state.value}")
        self.task = LibraryImportTaskRecord(
            id=self.task.id,
            library_id=self.task.library_id,
            state=state,
            resource_id=self.task.resource_id,
            source_node_id=self.task.source_node_id,
            owner_import_run_id=self.task.owner_import_run_id,
            role=self.task.role,
            attempt_count=self.task.attempt_count + (1 if increment_attempt else 0),
        )

    def upsert_asset_candidate(self, *, import_run_id: str, **kwargs: object) -> None:
        self.events.append(f"candidate:{import_run_id}")
        self.asset_candidates.append(
            AssetCandidateRecord(
                import_run_id=import_run_id,
                library_id=str(kwargs.get("library_id")),
                source_node_id=str(kwargs.get("source_node_id")),
                role=kwargs["role"],  # type: ignore[arg-type]
                import_state=kwargs["import_state"],  # type: ignore[arg-type]
                sequence_index=kwargs.get("sequence_index"),  # type: ignore[arg-type]
                sort_key=kwargs.get("sort_key"),  # type: ignore[arg-type]
                failure_reason=kwargs.get("failure_reason"),  # type: ignore[arg-type]
            )
        )

    def count_ready_asset_candidates(self, import_run_id: str) -> int:
        return sum(
            1
            for c in self.asset_candidates
            if c.import_run_id == import_run_id
            and c.import_state is AssetImportState.READY
        )

    def list_ready_asset_candidates(
        self, import_run_id: str
    ) -> tuple[AssetCandidateRecord, ...]:
        return tuple(
            c
            for c in self.asset_candidates
            if c.import_run_id == import_run_id
            and c.import_state is AssetImportState.READY
        )

    def count_incomplete_tasks(self, owner_import_run_id: str) -> int:
        return self.incomplete

    def count_failed_tasks(self, owner_import_run_id: str) -> int:
        return self.failed

    def set_run_state(
        self,
        run_id: str,
        state: ImportRunState,
        *,
        error_summary: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        self.run_states.append(state)
        self.events.append(f"run:{state.value}")

    def cleanup_run_candidates(self, run_id: str) -> None:
        self.events.append(f"cleanup_candidates:{run_id}")


class FakeAdapters:
    def __init__(self, result: FileParseResult) -> None:
        self._result = result
        self.parse_calls = 0

    def parse_file(self, **kwargs: object) -> FileParseResult:
        self.parse_calls += 1
        return self._result


class FakeQueue:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.completed = False
        self.write_guard_hits = 0

    def is_claim_valid(self, claim: ClaimedWork) -> bool:
        return self.valid

    def complete(self, claim: ClaimedWork) -> bool:
        self.completed = True
        return True

    def queued_item_count(self) -> int:
        return 0

    def enqueue_library_import_task(self, task_id: str) -> None:
        return None

    def enqueue_library_scan(self, library_id: str) -> None:
        return None

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> None:
        return None

    def heartbeat(self, claim: ClaimedWork) -> bool:
        return True


class FakeClock:
    def now(self) -> datetime:
        return _now()


class FakeLog:
    def emit(self, event: str, **kwargs: object) -> None:
        return None


class FakeSidecar:
    def __init__(self) -> None:
        self.scheduled: list[str] = []

    def schedule_after_commit(self, resource_id: str) -> None:
        self.scheduled.append(resource_id)


def _claim(task_id: str = "task-1") -> ClaimedWork:
    return ClaimedWork(
        work_item_id="work-1",
        work_kind="import",
        target_id=task_id,
        lease_owner="worker-a",
        lease_expires_at=_now(),
        scan_job_id=None,
        bridge_import_task_id=task_id,
    )


def _ok_parse() -> FileParseResult:
    adapter = _epub_adapter()
    return FileParseResult(
        ok=True,
        adapter=adapter,
        resource_title="Novel",
        asset=ParsedAssetPayload(
            title="Novel",
            role=AssetRole.PRIMARY,
            sequence_index=None,
            sort_key=None,
            mime_type="application/epub+zip",
            duration_ms=None,
            failure_reason=None,
            technical=AssetTechnicalMetadata(),
        ),
        error_code=None,
        error_summary=None,
    )


def _build(
    tmp_path: Path,
    *,
    resource: ReadableResourceRecord,
    task: LibraryImportTaskRecord,
    claim_valid: bool = True,
) -> tuple[ProcessReadableResourceImportTask, TrackingBooks, TrackingImportRuns, FakeQueue]:
    node = SourceNodeRecord(
        id="node-1",
        library_id="lib-1",
        parent_id=None,
        relative_path="Novel.epub",
        path_key="v1:x",
        name="Novel.epub",
        physical_kind=SourceNodePhysicalKind.REGULAR_FILE,
        observed_size_bytes=10,
        observed_mtime_ns=1,
        observed_at=_now(),
    )
    books = TrackingBooks(resource)
    runs = TrackingImportRuns(task)
    queue = FakeQueue(valid=claim_valid)
    usecase = ProcessReadableResourceImportTask(
        libraries=FakeLibraries(tmp_path),
        filesystem=FakeFilesystem(),
        source_nodes=FakeSourceNodes(node),
        books_resources=books,
        import_runs=runs,
        adapters=FakeAdapters(_ok_parse()),
        queue=queue,
        uow=SimpleUoW(),
        clock=FakeClock(),
        log=FakeLog(),
        sidecar=FakeSidecar(),
    )
    return usecase, books, runs, queue


def test_ready_reimport_writes_candidates_until_publish(tmp_path: Path) -> None:
    """READY resource reimport keeps published assets isolated until publish."""
    old_run = "run-old"
    new_run = "run-new"
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
        import_state=ResourceImportState.READY,
        published_run_id=old_run,
        active_import_run_id=new_run,
    )
    task = LibraryImportTaskRecord(
        id="task-1",
        library_id="lib-1",
        state=LibraryImportTaskState.QUEUED,
        resource_id="res-1",
        source_node_id="node-1",
        owner_import_run_id=new_run,
        role=AssetRole.PRIMARY,
        attempt_count=0,
    )
    usecase, books, runs, queue = _build(tmp_path, resource=resource, task=task)
    result = usecase.execute("task-1", _claim())
    assert result.outcome == "ok"
    assert any(e.startswith("candidate:") for e in runs.events)
    assert books.publish_calls == [new_run]
    assert books.upsert_asset_calls == [new_run]
    assert books.resource.published_run_id == new_run
    assert old_run not in books.publish_calls
    assert queue.completed is True


def test_late_invalid_claim_skips_writes(tmp_path: Path) -> None:
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
        import_state=ResourceImportState.PENDING,
        published_run_id=None,
        active_import_run_id="run-new",
    )
    task = LibraryImportTaskRecord(
        id="task-1",
        library_id="lib-1",
        state=LibraryImportTaskState.QUEUED,
        resource_id="res-1",
        source_node_id="node-1",
        owner_import_run_id="run-new",
        role=AssetRole.PRIMARY,
        attempt_count=0,
    )
    usecase, books, runs, queue = _build(
        tmp_path, resource=resource, task=task, claim_valid=False
    )
    result = usecase.execute("task-1", _claim())
    assert result.outcome == "lease_invalid"
    assert runs.asset_candidates == []
    assert books.publish_calls == []
    assert books.upsert_asset_calls == []
    assert queue.completed is False
