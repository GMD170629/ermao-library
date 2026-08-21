"""ReimportSourceNode and RetryReadableResourceImport use cases."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    adapter_identity,
    BookResourceRepositoryPort,
    ClockPort,
    ImportRunRepositoryPort,
    LibraryConfigPort,
    ObservedSourceEntry,
    PipelineLogPort,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
    WorkQueuePort,
)
from app.modules.imports.domain.directory_probe import ProbeInterpretationResult
from app.modules.imports.domain.import_run_policies import ImportRunKind, ImportRunState
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)


@dataclass(frozen=True, slots=True)
class ReimportResult:
    ok: bool
    run_id: str | None
    code: str | None = None


class ReimportSourceNode:
    def __init__(
        self,
        *,
        libraries: LibraryConfigPort,
        filesystem: SourceTreeFilesystemPort,
        source_nodes: SourceNodeRepositoryPort,
        books_resources: BookResourceRepositoryPort,
        import_runs: ImportRunRepositoryPort,
        queue: WorkQueuePort,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        log: PipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._import_runs = import_runs
        self._queue = queue
        self._uow = uow
        self._clock = clock
        self._log = log

    def execute(self, source_node_id: str) -> ReimportResult:
        try:
            return self._execute(source_node_id)
        except Exception:
            self._uow.rollback()
            raise

    def _execute(self, source_node_id: str) -> ReimportResult:
        with self._uow.transaction():
            node = self._source_nodes.get(source_node_id)
            if node is None:
                return ReimportResult(ok=False, run_id=None, code="SOURCE_NODE_NOT_FOUND")
            config = self._libraries.get_library(node.library_id)
            resource = self._books_resources.get_resource_by_source_node(source_node_id)
            library_id = node.library_id
            node_name = node.name
            relative_path = node.relative_path
            physical_kind = node.physical_kind
            root_path = config.root_path
            ignore_hidden = config.ignore_hidden
            ignore_patterns = config.ignore_patterns
            global_ignore_patterns = config.global_ignore_patterns
            probe_sample_limit = config.probe_sample_limit
            probe_max_entries = config.probe_max_entries
            probe_max_depth = config.probe_max_depth
            probe_time_budget_ms = config.probe_time_budget_ms
            resource_id = resource.id if resource else None
            expected_active = resource.active_import_run_id if resource else None

        parent_rel = (
            None if "/" not in relative_path else relative_path.rsplit("/", 1)[0]
        )
        parent_abs = (
            root_path
            if parent_rel is None
            else self._filesystem.resolve_under_root(root_path, parent_rel)
        )

        observed_kind = physical_kind
        observed_size: int | None = None
        observed_mtime_ns: int | None = None
        self._uow.release_before_io()
        for name, kind, size, mtime_ns in self._filesystem.iter_directory_entries(
            parent_abs
        ):
            if name != node_name:
                continue
            observed_kind = kind
            observed_size = size
            observed_mtime_ns = mtime_ns
            break

        adapter = None
        sample_paths: tuple[str, ...] = ()
        self._uow.release_before_io()
        if observed_kind is SourceNodePhysicalKind.REGULAR_FILE:
            adapter = unique_adapter_or_none(match_file_adapters(node_name))
            sample_paths = (relative_path,)
        elif observed_kind is SourceNodePhysicalKind.DIRECTORY:
            decision, _ = self._filesystem.probe_directory(
                root=root_path,
                directory_relative_path=relative_path,
                ignore_hidden=ignore_hidden,
                ignore_patterns=ignore_patterns,
                global_ignore_patterns=global_ignore_patterns,
                sample_limit=probe_sample_limit,
                max_entries=probe_max_entries,
                max_depth=probe_max_depth,
                time_budget_ms=probe_time_budget_ms,
            )
            if decision.result is ProbeInterpretationResult.RESOURCE:
                adapter = decision.adapter
                sample_paths = decision.evidence.sample_relative_paths

        if adapter is None:
            return ReimportResult(ok=False, run_id=None, code="NO_UNIQUE_ADAPTER")

        with self._uow.transaction():
            if observed_mtime_ns is not None:
                self._source_nodes.refresh_observed(
                    source_node_id,
                    ObservedSourceEntry(
                        relative_path=SourceNodeRelativePath(relative_path),
                        physical_kind=observed_kind,
                        observed_size_bytes=observed_size,
                        observed_mtime_ns=observed_mtime_ns,
                        observed_at=self._clock.now(),
                    ),
                )
            run_id = self._import_runs.create_run(
                library_id=library_id,
                kind=ImportRunKind.REIMPORT,
                source_node_id=source_node_id,
                resource_id=resource_id,
                adapter_id=adapter.adapter_id.value,
                adapter_version=adapter.adapter_version,
            )
            if resource_id is not None:
                cas_ok = self._books_resources.cas_set_active_import_run(
                    resource_id,
                    expected_active_run_id=expected_active,
                    new_active_run_id=run_id,
                )
                if not cas_ok:
                    self._import_runs.set_run_state(
                        run_id,
                        ImportRunState.FAILED,
                        error_summary="active_run_cas_failed",
                    )
                    return ReimportResult(
                        ok=False, run_id=run_id, code="ACTIVE_RUN_BUSY"
                    )
                target_resource_id = resource_id
            else:
                book_id = self._books_resources.ensure_book(
                    library_id=library_id,
                    source_node_id=source_node_id,
                    title=node_name,
                )
                created = self._books_resources.create_pending_resource(
                    library_id=library_id,
                    book_id=book_id,
                    source_node_id=source_node_id,
                    adapter=adapter_identity(adapter),
                    active_import_run_id=run_id,
                )
                self._import_runs.attach_resource(run_id, created.id)
                target_resource_id = created.id

            self._import_runs.upsert_resource_candidate(
                import_run_id=run_id,
                library_id=library_id,
                book_id=None,
                source_node_id=source_node_id,
                adapter=adapter,
                title=node_name,
            )
            enqueued = 0
            for sample in sample_paths:
                sample_node = self._source_nodes.get_by_path_key(
                    library_id, SourceNodeRelativePath(sample).path_key
                )
                asset_source_id = (
                    sample_node.id if sample_node is not None else source_node_id
                )
                task = self._import_runs.create_task(
                    library_id=library_id,
                    resource_id=target_resource_id,
                    source_node_id=asset_source_id,
                    owner_import_run_id=run_id,
                    role=adapter.asset_role,
                )
                self._queue.enqueue_library_import_task(task.id)
                enqueued += 1
            if enqueued == 0:
                task = self._import_runs.create_task(
                    library_id=library_id,
                    resource_id=target_resource_id,
                    source_node_id=source_node_id,
                    owner_import_run_id=run_id,
                    role=adapter.asset_role,
                )
                self._queue.enqueue_library_import_task(task.id)

        self._log.emit(
            "readable_resource.reimport.started",
            library_id=library_id,
            resource_id=target_resource_id,
            run_id=run_id,
            stage="reimport",
            outcome="ok",
        )
        return ReimportResult(ok=True, run_id=run_id)


class RetryReadableResourceImport:
    def __init__(
        self,
        *,
        books_resources: BookResourceRepositoryPort,
        import_runs: ImportRunRepositoryPort,
        source_nodes: SourceNodeRepositoryPort,
        queue: WorkQueuePort,
        uow: UnitOfWorkPort,
        log: PipelineLogPort,
    ) -> None:
        self._books_resources = books_resources
        self._import_runs = import_runs
        self._source_nodes = source_nodes
        self._queue = queue
        self._uow = uow
        self._log = log

    def execute(self, resource_id: str) -> ReimportResult:
        try:
            return self._execute(resource_id)
        except Exception:
            self._uow.rollback()
            raise

    def _execute(self, resource_id: str) -> ReimportResult:
        with self._uow.transaction():
            resource = self._books_resources.get_resource(resource_id)
            if resource is None:
                return ReimportResult(ok=False, run_id=None, code="RESOURCE_NOT_FOUND")
            adapter = next(
                (
                    spec
                    for spec in ADAPTER_SPECS
                    if spec.adapter_id.value == resource.adapter_id
                ),
                None,
            )
            if adapter is None:
                return ReimportResult(ok=False, run_id=None, code="UNKNOWN_ADAPTER")
            run_id = self._import_runs.create_run(
                library_id=resource.library_id,
                kind=ImportRunKind.RETRY,
                source_node_id=resource.source_node_id,
                resource_id=resource.id,
                adapter_id=adapter.adapter_id.value,
                adapter_version=adapter.adapter_version,
            )
            if not self._books_resources.cas_set_active_import_run(
                resource.id,
                expected_active_run_id=None,
                new_active_run_id=run_id,
            ):
                self._import_runs.set_run_state(
                    run_id,
                    ImportRunState.FAILED,
                    error_summary="active_run_cas_failed",
                )
                return ReimportResult(ok=False, run_id=run_id, code="ACTIVE_RUN_BUSY")
            task = self._import_runs.create_task(
                library_id=resource.library_id,
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                owner_import_run_id=run_id,
                role=adapter.asset_role,
            )
            self._queue.enqueue_library_import_task(task.id)
            library_id = resource.library_id

        self._log.emit(
            "readable_resource.retry.started",
            library_id=library_id,
            resource_id=resource_id,
            run_id=run_id,
            stage="retry",
            outcome="ok",
        )
        return ReimportResult(ok=True, run_id=run_id)
