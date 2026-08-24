from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    AssetTechnicalMetadata,
    BookResourceRepositoryPort,
    ClockPort,
    FileParseResult,
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    ParsedAssetPayload,
    PipelineLogPort,
    ResourceAdapterExecutorPort,
    SidecarWritebackPort,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.domain.resource_adapters import ADAPTER_SPECS
from app.modules.imports.infrastructure.readable_resource.support import (
    BestEffortSidecarWriteback,
    InMemorySidecarWriteback,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import (
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
)
from app.modules.library.public import (
    LibrarySourceTreeConfig,
    ReadableResourceRecord,
    SourceNodeRecord,
)


@dataclass
class _Clock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(UTC)


class _Uow(UnitOfWorkPort):
    def __init__(self) -> None:
        self.commits = 0

    @contextmanager
    def transaction(self):
        yield
        self.commits += 1

    def release_before_io(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _Libraries(LibraryConfigPort):
    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        return LibrarySourceTreeConfig(
            library_id=library_id,
            root_path=Path("/library"),
            organization_mode=TargetLibraryOrganizationMode.FLAT,
            ignore_hidden=True,
            ignore_patterns=None,
            global_ignore_patterns="",
            probe_sample_limit=10,
            probe_max_entries=100,
            probe_max_depth=4,
            probe_time_budget_ms=1000,
        )

    def source_node_count(self, library_id: str) -> int:
        return 1

    def update_organization_mode(self, library_id, mode):
        return None

    def update_root_path(self, library_id, root_path):
        return None

    def root_path_conflicts(self, root_path, *, exclude_library_id):
        return False


class _SourceNodes(SourceNodeRepositoryPort):
    def __init__(self, node: SourceNodeRecord) -> None:
        self.node = node

    def get(self, source_node_id: str) -> SourceNodeRecord | None:
        return self.node if source_node_id == self.node.id else None

    def get_by_path_key(self, library_id, path_key):
        return None

    def insert_if_absent(self, *, library_id, parent_id, entry):
        raise AssertionError("not used by asset import")

    def list_subtree_ids(self, source_node_id):
        return (source_node_id,)

    def delete_subtree(self, source_node_id):
        return None

    def get_interpretation(self, source_node_id):
        return None

    def upsert_interpretation(self, **kwargs):
        return None


class _LibrariesResources(BookResourceRepositoryPort):
    def __init__(self, resource: ReadableResourceRecord) -> None:
        self.resource = resource
        self.asset_ready = 0
        self.resource_ready = False
        self.failed = False

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None:
        return self.resource if resource_id == self.resource.id else None

    def get_resource_by_source_node(self, source_node_id):
        return self.resource if source_node_id == self.resource.source_node_id else None

    def ensure_book(self, **kwargs):
        return self.resource.book_id

    def get_book_id_for_source_node(self, source_node_id):
        return self.resource.book_id

    def create_pending_resource(self, **kwargs):
        return self.resource

    def set_enablement(self, resource_id, state):
        return None

    def mark_resource_ready(self, *, resource_id, title=None):
        self.resource_ready = True

    def mark_resource_failed(self, resource_id):
        self.failed = True

    def upsert_asset(self, **kwargs):
        self.asset_ready = 1
        return "asset-created"

    def count_ready_assets(self, resource_id):
        return self.asset_ready

    def find_outermost_directory_resource(self, library_id, relative_path):
        return None

    def delete_library_overlay_rows(self, library_id):
        return None

    def delete_assets_for_source_nodes(self, source_node_ids):
        return ()

    def reevaluate_ready_after_asset_loss(self, resource_ids):
        return None


class _Queue(LibraryImportTaskQueuePort):
    def __init__(self, task: LibraryImportTaskRecord) -> None:
        self.task = task
        self.succeeded = False
        self.failed: str | None = None

    def get_task(self, task_id: str):
        return self.task if task_id == self.task.id else None

    def mark_succeeded(self, task_id, *, finished_at):
        self.succeeded = True

    def mark_failed(self, task_id, *, error_summary, finished_at):
        self.failed = error_summary

    def enqueue(self, **kwargs):
        raise AssertionError("not used by asset import")

    def ensure_import_asset_task(self, **kwargs):
        raise AssertionError("not used by asset import")

    def next_queued(self):
        return self.task

    def mark_running(self, task_id, *, started_at):
        return None

    def fail_interrupted_tasks_on_startup(self, *, finished_at):
        return 0

    def requeue_failed_for_library(self, library_id):
        return 0

    def requeue_failed_for_source(self, source_node_id):
        return 0

    def has_active_kind(self, **kwargs):
        return False


class _Filesystem(SourceTreeFilesystemPort):
    def __init__(self, source: Path) -> None:
        self.source = source

    def resolve_under_root(self, root: Path, relative_path: str) -> Path:
        return self.source

    def iter_directory_entries(self, absolute_directory):
        return iter(())

    def probe_directory(self, **kwargs):
        raise AssertionError("not used by asset import")

    def path_is_readable_directory(self, path):
        return False


class _Adapters(ResourceAdapterExecutorPort):
    def parse_file(self, *, absolute_path, adapter, role, **_kwargs):
        return FileParseResult(
            ok=True,
            adapter=adapter,
            resource_title="Parsed resource",
            asset=ParsedAssetPayload(
                title="Parsed asset",
                role=AssetRole.PRIMARY,
                sequence_index=0,
                sort_key="0000",
                mime_type="text/plain",
                duration_ms=None,
                failure_reason=None,
                technical=AssetTechnicalMetadata(),
            ),
            error_code=None,
            error_summary=None,
        )


class _Log(PipelineLogPort):
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs.get("outcome")))


def _pipeline(source: Path, sidecar: SidecarWritebackPort, uow: _Uow):
    adapter = ADAPTER_SPECS[2]
    node = SourceNodeRecord(
        id="sidecar-node",
        library_id="test-library",
        parent_id=None,
        relative_path="books/sidecar.txt",
        path_key="v1:" + "b" * 64,
        name="sidecar.txt",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=source.stat().st_size,
        observed_mtime_ns=source.stat().st_mtime_ns,
        observed_at=datetime.now(UTC),
    )
    resource = ReadableResourceRecord(
        id="sidecar-resource",
        library_id="test-library",
        book_id="sidecar-book",
        source_node_id=node.id,
        adapter_id=adapter.adapter_id.value,
        adapter_version=adapter.adapter_version,
        media_kind=adapter.media_kind,
        format=adapter.format_label,
        enablement_state=ResourceEnablementState.ENABLED,
        import_state=ResourceImportState.PENDING,
    )
    task = LibraryImportTaskRecord(
        id="sidecar-task",
        kind="IMPORT_ASSET",
        library_id="test-library",
        state="QUEUED",
        resource_id=resource.id,
        source_node_id=node.id,
        role=AssetRole.PRIMARY,
        error_summary=None,
    )
    queue = _Queue(task)
    resources = _LibrariesResources(resource)
    pipeline = ProcessReadableResourceImportTask(
        libraries=_Libraries(),
        filesystem=_Filesystem(source),
        source_nodes=_SourceNodes(node),
        books_resources=resources,
        adapters=_Adapters(),
        queue=queue,
        uow=uow,
        clock=_Clock(),
        log=_Log(),
        sidecar=sidecar,
    )
    return pipeline, queue, resources


def test_sidecar_is_scheduled_only_after_resource_asset_commit(tmp_path: Path) -> None:
    source = tmp_path / "sidecar.txt"
    source.write_text("content")
    uow = _Uow()
    sidecar = InMemorySidecarWriteback()
    pipeline, queue, resources = _pipeline(source, sidecar, uow)

    result = pipeline.execute("sidecar-task")

    assert result.outcome == "ok"
    assert queue.succeeded is True
    assert resources.asset_ready == 1
    assert resources.resource_ready is True
    assert uow.commits == 3
    assert sidecar.scheduled == ["sidecar-resource"]


def test_sidecar_failure_is_recorded_without_rolling_back_committed_asset(
    tmp_path: Path,
    caplog,
) -> None:
    source = tmp_path / "sidecar.txt"
    source.write_text("content")
    uow = _Uow()

    def fail_sidecar(_resource_id: str) -> None:
        raise OSError("sidecar unavailable")

    sidecar = BestEffortSidecarWriteback(fail_sidecar)
    pipeline, queue, resources = _pipeline(source, sidecar, uow)

    with caplog.at_level("ERROR", logger="ermao.readable_resource_pipeline"):
        result = pipeline.execute("sidecar-task")

    assert result.outcome == "ok"
    assert queue.succeeded is True
    assert resources.asset_ready == 1
    assert uow.commits == 3
    assert "readable_resource.sidecar.failed" in caplog.text
