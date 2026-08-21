"""ReimportSourceNode and RetryReadableResourceImport use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    file_extension,
    match_file_adapters,
    unique_adapter_or_none,
    ResourceAdapterSpec,
)
from app.modules.library.domain.readable_resource_states import AssetImportState
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    parse_source_node_relative_path,
)

_REIMPORT_COMMIT_BATCH = 32


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
            if resource is not None and resource.active_import_run_id is not None:
                # Busy: no FS I/O and no Run creation.
                return ReimportResult(ok=False, run_id=None, code="ACTIVE_RUN_BUSY")
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
        self._uow.release_before_io()
        if observed_kind is SourceNodePhysicalKind.REGULAR_FILE:
            adapter = unique_adapter_or_none(match_file_adapters(node_name))
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
                resource_id=None,
                adapter_id=adapter.adapter_id.value,
                adapter_version=adapter.adapter_version,
            )
            if resource_id is not None:
                cas_ok = self._books_resources.cas_set_active_import_run(
                    resource_id,
                    expected_active_run_id=None,
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
                self._import_runs.attach_resource(run_id, resource_id)
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

        if observed_kind is SourceNodePhysicalKind.REGULAR_FILE:
            with self._uow.transaction():
                task = self._import_runs.create_task(
                    library_id=library_id,
                    resource_id=target_resource_id,
                    source_node_id=source_node_id,
                    owner_import_run_id=run_id,
                    role=adapter.asset_role,
                )
                self._queue.enqueue_library_import_task(task.id)
                self._import_runs.mark_discovery_complete(run_id)
        else:
            self._discover_directory_scope(
                library_id=library_id,
                root_path=root_path,
                directory_source_node_id=source_node_id,
                directory_relative_path=relative_path,
                ignore_hidden=ignore_hidden,
                ignore_patterns=ignore_patterns,
                global_ignore_patterns=global_ignore_patterns,
                adapter=adapter,
                target_resource_id=target_resource_id,
                run_id=run_id,
            )

        self._log.emit(
            "readable_resource.reimport.started",
            library_id=library_id,
            resource_id=target_resource_id,
            run_id=run_id,
            stage="reimport",
            outcome="ok",
        )
        return ReimportResult(ok=True, run_id=run_id)

    def _discover_directory_scope(
        self,
        *,
        library_id: str,
        root_path: object,
        directory_source_node_id: str,
        directory_relative_path: str,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
        adapter: ResourceAdapterSpec,
        target_resource_id: str,
        run_id: str,
    ) -> None:
        root = Path(str(root_path))
        stack: list[tuple[str, str]] = [
            (directory_source_node_id, directory_relative_path)
        ]
        batch = 0

        while stack:
            parent_id, parent_rel = stack.pop()
            absolute = self._filesystem.resolve_under_root(root, parent_rel)
            self._uow.release_before_io()
            try:
                entries = list(self._filesystem.iter_directory_entries(absolute))
            except OSError:
                continue

            for name, kind, size, mtime_ns in entries:
                if ignore_hidden and name.startswith(".") and name not in {".", ".."}:
                    continue
                relative = f"{parent_rel}/{name}"
                if self._matches_ignore(
                    relative, name, ignore_patterns, global_ignore_patterns
                ):
                    continue
                parsed = parse_source_node_relative_path(relative)
                if not isinstance(parsed, SourceNodeRelativePath):
                    continue

                entry = ObservedSourceEntry(
                    relative_path=parsed,
                    physical_kind=kind,
                    observed_size_bytes=size,
                    observed_mtime_ns=mtime_ns,
                    observed_at=self._clock.now(),
                )

                with self._uow.transaction():
                    existing = self._source_nodes.get_by_path_key(
                        library_id, parsed.path_key
                    )
                    if existing is not None:
                        node = existing
                        self._source_nodes.refresh_observed(existing.id, entry)
                        created = False
                    else:
                        node, created = self._source_nodes.insert_if_absent(
                            library_id=library_id,
                            parent_id=parent_id,
                            entry=entry,
                        )
                    del created

                    if kind is SourceNodePhysicalKind.DIRECTORY:
                        stack.append((node.id, parsed.value))
                    elif kind is SourceNodePhysicalKind.REGULAR_FILE:
                        if file_extension(parsed.name) in adapter.file_extensions:
                            self._import_runs.upsert_asset_candidate(
                                import_run_id=run_id,
                                library_id=library_id,
                                source_node_id=node.id,
                                role=adapter.asset_role,
                                import_state=AssetImportState.PENDING,
                                sequence_index=None,
                                sort_key=parsed.name,
                                failure_reason=None,
                            )
                            task = self._import_runs.create_task(
                                library_id=library_id,
                                resource_id=target_resource_id,
                                source_node_id=node.id,
                                owner_import_run_id=run_id,
                                role=adapter.asset_role,
                            )
                            self._queue.enqueue_library_import_task(task.id)
                    batch += 1
                    if batch >= _REIMPORT_COMMIT_BATCH:
                        batch = 0

        with self._uow.transaction():
            self._import_runs.mark_discovery_complete(run_id)

    def _matches_ignore(
        self,
        relative: str,
        name: str,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
    ) -> bool:
        for patterns in (global_ignore_patterns, ignore_patterns or ""):
            for pattern in patterns.splitlines():
                pattern = pattern.strip()
                if not pattern:
                    continue
                if pattern == name or pattern == relative or relative.endswith(
                    "/" + pattern
                ):
                    return True
        return False


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
            if resource.active_import_run_id is not None:
                return ReimportResult(ok=False, run_id=None, code="ACTIVE_RUN_BUSY")
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
                resource_id=None,
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
            self._import_runs.attach_resource(run_id, resource.id)
            task = self._import_runs.create_task(
                library_id=resource.library_id,
                resource_id=resource.id,
                source_node_id=resource.source_node_id,
                owner_import_run_id=run_id,
                role=adapter.asset_role,
            )
            self._queue.enqueue_library_import_task(task.id)
            self._import_runs.mark_discovery_complete(run_id)
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
