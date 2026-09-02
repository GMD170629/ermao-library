"""Continue-import scan: streaming SourceNode discovery and task enqueue."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    BookResourceRepositoryPort,
    ClockPort,
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    PipelineLogPort,
    ReadableResourceRecord,
    RegularFileObservation,
    SourceNodeDeletionPort,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
    UnreadableDirectoryEntry,
    adapter_identity,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeInterpretationResult,
)
from app.modules.imports.domain.ignore_rules import should_ignore_source_entry
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    ResourceAdapterSpec,
    file_extension,
    is_supported_source_tree_filename,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
from app.modules.library.public import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeViolationCode,
    decide_book_anchor_for_resource,
    evaluate_path_key_occupancy,
    parse_source_node_relative_path,
    resource_root_folder_creates_empty_book_on_discovery,
)


@dataclass(frozen=True, slots=True)
class ScanLibrarySourceTreeResult:
    library_id: str
    nodes_inserted: int
    resources_created: int
    tasks_enqueued: int
    path_key_collisions: int


class SourceScanStartUnavailableError(RuntimeError):
    code = "SOURCE_SCAN_START_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class ScanLibrarySourceTree:
    """Execute SCAN_LIBRARY / CONTINUE_SOURCE work for one consumer."""

    def __init__(
        self,
        *,
        libraries: LibraryConfigPort,
        filesystem: SourceTreeFilesystemPort,
        source_nodes: SourceNodeRepositoryPort,
        books_resources: BookResourceRepositoryPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        log: PipelineLogPort,
        source_node_deletion: SourceNodeDeletionPort | None = None,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._queue = queue
        self._uow = uow
        self._clock = clock
        self._log = log
        self._source_node_deletion = source_node_deletion

    def execute_library(
        self,
        library_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
    ) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            config = self._libraries.get_library(library_id)
        self._require_readable_directory(config.root_path)
        return self._walk(
            config=config,
            start_parent_id=None,
            start_parent_rel=None,
            task_id=task_id,
            missing_entry_policy=missing_entry_policy,
        )

    def execute_source(
        self,
        source_node_id: str,
        *,
        task_id: str | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
    ) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            node = self._source_nodes.get(source_node_id)
            if node is None:
                raise LookupError(source_node_id)
            config = self._libraries.get_library(node.library_id)
            relative = SourceNodeRelativePath(node.relative_path)

        absolute = self._filesystem.resolve_under_root(config.root_path, relative.value)
        self._uow.release_before_io()
        file_observation: RegularFileObservation | None = None
        if node.physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
            file_observation = self._filesystem.observe_readable_file(absolute)
            if file_observation is None:
                raise SourceScanStartUnavailableError
        elif node.physical_kind is SourceNodePhysicalKind.DIRECTORY:
            self._require_readable_directory(absolute)

        if self._should_ignore(
            config,
            relative.parent_relative_path,
            relative.name,
            node.physical_kind,
        ):
            return ScanLibrarySourceTreeResult(
                library_id=config.library_id,
                nodes_inserted=0,
                resources_created=0,
                tasks_enqueued=0,
                path_key_collisions=0,
            )

        if node.physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
            if file_observation is None:
                raise AssertionError("regular file observation was not captured")
            with self._uow.transaction():
                _, observation_changed = self._source_nodes.refresh_observation(
                    source_node_id=node.id,
                    entry=ObservedSourceEntry(
                        relative_path=relative,
                        physical_kind=SourceNodePhysicalKind.REGULAR_FILE,
                        observed_size_bytes=file_observation.observed_size_bytes,
                        observed_mtime_ns=file_observation.observed_mtime_ns,
                        observed_at=self._clock.now(),
                    ),
                )
                resources, tasks = self._process_regular_file(
                    config,
                    node.id,
                    relative,
                    observation_changed=observation_changed,
                )
            return ScanLibrarySourceTreeResult(
                library_id=config.library_id,
                nodes_inserted=0,
                resources_created=resources,
                tasks_enqueued=tasks,
                path_key_collisions=0,
            )
        if node.physical_kind is SourceNodePhysicalKind.DIRECTORY:
            with self._uow.transaction():
                covered = self._books_resources.find_outermost_directory_resource(
                    config.library_id, relative.value
                )
            if covered is None:
                self._probe_and_persist_directory(
                    config, node.id, relative, task_id=task_id
                )
            else:
                with self._uow.transaction():
                    self._mark_node_covered_by_directory_resource(node.id)
            return self._walk(
                config=config,
                start_parent_id=node.id,
                start_parent_rel=relative.value,
                task_id=task_id,
                missing_entry_policy=missing_entry_policy,
            )
        return ScanLibrarySourceTreeResult(
            library_id=config.library_id,
            nodes_inserted=0,
            resources_created=0,
            tasks_enqueued=0,
            path_key_collisions=0,
        )

    def _walk(
        self,
        *,
        config: LibrarySourceTreeConfig,
        start_parent_id: str | None,
        start_parent_rel: str | None,
        task_id: str | None,
        missing_entry_policy: MissingEntryPolicy,
    ) -> ScanLibrarySourceTreeResult:
        inserted = 0
        resources_created = 0
        tasks_enqueued = 0
        collisions = 0
        stack: list[tuple[str | None, str | None]] = [
            (start_parent_id, start_parent_rel)
        ]

        while stack:
            if self._task_was_cancelled(task_id):
                break
            parent_id, parent_rel = stack.pop()
            absolute = (
                config.root_path
                if parent_rel is None
                else self._filesystem.resolve_under_root(config.root_path, parent_rel)
            )
            self._uow.release_before_io()
            try:
                directory_entries = self._filesystem.iter_directory_entries(absolute)
            except OSError:
                self._log.emit(
                    "source_tree.scan.directory_unreadable",
                    library_id=config.library_id,
                    stage="scan",
                    outcome="io_error",
                )
                if (parent_id, parent_rel) == (start_parent_id, start_parent_rel):
                    raise SourceScanStartUnavailableError
                continue

            seen_path_keys: set[str] = set()
            iteration_completed = False
            observed_any_entry = False

            while True:
                try:
                    observed = next(directory_entries)
                except StopIteration:
                    iteration_completed = True
                    break
                except OSError as error:
                    self._log.emit(
                        "source_tree.scan.directory_unreadable",
                        library_id=config.library_id,
                        stage="scan",
                        outcome="io_error",
                    )
                    if not observed_any_entry and (parent_id, parent_rel) == (
                        start_parent_id,
                        start_parent_rel,
                    ):
                        raise SourceScanStartUnavailableError from error
                    break

                observed_any_entry = True

                if isinstance(observed, UnreadableDirectoryEntry):
                    relative_str = (
                        observed.name
                        if parent_rel is None
                        else f"{parent_rel}/{observed.name}"
                    )
                    protected = parse_source_node_relative_path(relative_str)
                    if isinstance(protected, SourceNodeRelativePath):
                        seen_path_keys.add(protected.path_key)
                    continue

                name, kind, size, mtime_ns = observed

                if self._should_ignore(config, parent_rel, name, kind):
                    continue
                relative_str = name if parent_rel is None else f"{parent_rel}/{name}"
                parsed = parse_source_node_relative_path(relative_str)
                if not isinstance(parsed, SourceNodeRelativePath):
                    continue
                seen_path_keys.add(parsed.path_key)

                entry = ObservedSourceEntry(
                    relative_path=parsed,
                    physical_kind=kind,
                    observed_size_bytes=size,
                    observed_mtime_ns=mtime_ns,
                    observed_at=self._clock.now(),
                )

                with self._uow.transaction():
                    existing = self._source_nodes.get_by_path_key(
                        config.library_id, parsed.path_key
                    )
                    if existing is not None:
                        collision = evaluate_path_key_occupancy(
                            occupied_relative_path=SourceNodeRelativePath(
                                existing.relative_path
                            ),
                            candidate_relative_path=parsed,
                        )
                        if collision is not None:
                            collisions += 1
                            self._log.emit(
                                "source_tree.scan.path_key_collision",
                                library_id=config.library_id,
                                stage="scan",
                                outcome=SourceNodeViolationCode.PATH_KEY_COLLISION.value,
                            )
                            continue
                        node, observation_changed = (
                            self._source_nodes.refresh_observation(
                                source_node_id=existing.id,
                                entry=entry,
                            )
                        )
                    else:
                        node, created = self._source_nodes.insert_if_absent(
                            library_id=config.library_id,
                            parent_id=parent_id,
                            entry=entry,
                        )
                        if created:
                            inserted += 1
                        observation_changed = False

                    if kind is SourceNodePhysicalKind.DIRECTORY:
                        if (
                            resource_root_folder_creates_empty_book_on_discovery(
                                config.organization_mode,
                                is_root_child_directory=parsed.is_root_child,
                            )
                            and self._books_resources.get_book_id_for_source_node(
                                node.id
                            )
                            is None
                        ):
                            self._books_resources.ensure_book(
                                library_id=config.library_id,
                                source_node_id=node.id,
                                title=parsed.name,
                            )
                        covered = (
                            self._books_resources.find_outermost_directory_resource(
                                config.library_id, parsed.value
                            )
                        )
                        needs_probe = covered is None
                    else:
                        needs_probe = False

                if kind is SourceNodePhysicalKind.DIRECTORY:
                    if needs_probe:
                        created_r, enqueued = self._probe_and_persist_directory(
                            config, node.id, parsed, task_id=task_id
                        )
                        resources_created += created_r
                        tasks_enqueued += enqueued
                    else:
                        with self._uow.transaction():
                            self._mark_node_covered_by_directory_resource(node.id)
                    stack.append((node.id, parsed.value))
                    continue

                if kind is SourceNodePhysicalKind.REGULAR_FILE:
                    with self._uow.transaction():
                        created_r, enqueued = self._process_regular_file(
                            config,
                            node.id,
                            parsed,
                            observation_changed=observation_changed,
                        )
                        resources_created += created_r
                        tasks_enqueued += enqueued

            if (
                iteration_completed
                and missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
                and not self._task_was_cancelled(task_id)
            ):
                self._prune_missing_children(
                    library_id=config.library_id,
                    parent_id=parent_id,
                    seen_path_keys=seen_path_keys,
                )

        self._log.emit(
            "source_tree.scan.completed",
            library_id=config.library_id,
            stage="scan",
            outcome="ok",
        )
        return ScanLibrarySourceTreeResult(
            library_id=config.library_id,
            nodes_inserted=inserted,
            resources_created=resources_created,
            tasks_enqueued=tasks_enqueued,
            path_key_collisions=collisions,
        )

    def _probe_and_persist_directory(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative: SourceNodeRelativePath,
        *,
        task_id: str | None,
    ) -> tuple[int, int]:
        self._uow.release_before_io()
        decision = self._filesystem.probe_directory(
            root=config.root_path,
            directory_relative_path=relative.value,
            ignore_hidden=config.ignore_hidden,
            ignore_patterns=config.ignore_patterns,
            global_ignore_patterns=config.global_ignore_patterns,
            sample_limit=config.probe_sample_limit,
            max_entries=config.probe_max_entries,
            max_depth=config.probe_max_depth,
            time_budget_ms=config.probe_time_budget_ms,
        )
        with self._uow.transaction():
            if self._task_was_cancelled_in_transaction(task_id):
                return (0, 0)
            changed = self._persist_directory_decision(
                config=config,
                node_id=node_id,
                relative_path=relative,
                decision=decision,
            )
            if decision.result is ProbeInterpretationResult.RESOURCE:
                return (
                    int(changed),
                    self._enqueue_directory_samples(config, node_id, decision),
                )
        return (0, 0)

    def _mark_node_covered_by_directory_resource(self, node_id: str) -> None:
        existing = self._books_resources.get_resource_by_source_node(node_id)
        if existing is not None:
            self._books_resources.delete_resource(existing.id)
        self._source_nodes.upsert_interpretation(
            source_node_id=node_id,
            result="NODE_ONLY",
            source="AUTO",
            adapter_id=None,
            adapter_version=None,
            reason_code="COVERED_BY_OUTER_DIRECTORY_RESOURCE",
            sample_relative_paths=None,
            sample_count=None,
            max_entries_visited=None,
            max_depth=None,
            time_budget_ms=None,
            termination_reason=None,
            recognized_at=self._clock.now(),
        )

    def _task_was_cancelled(self, task_id: str | None) -> bool:
        if task_id is None:
            return False
        with self._uow.transaction():
            return self._task_was_cancelled_in_transaction(task_id)

    def _task_was_cancelled_in_transaction(self, task_id: str | None) -> bool:
        if task_id is None:
            return False
        task = self._queue.get_task(task_id)
        return task is None

    def _should_ignore(
        self,
        config: LibrarySourceTreeConfig,
        parent_rel: str | None,
        name: str,
        physical_kind: SourceNodePhysicalKind,
    ) -> bool:
        relative = name if parent_rel is None else f"{parent_rel}/{name}"
        ignored = should_ignore_source_entry(
            relative_path=relative,
            name=name,
            is_regular_file=physical_kind is SourceNodePhysicalKind.REGULAR_FILE,
            ignore_hidden=config.ignore_hidden,
            library_patterns=config.ignore_patterns,
            global_patterns=config.global_ignore_patterns,
        )
        if ignored:
            return True
        return (
            physical_kind is SourceNodePhysicalKind.REGULAR_FILE
            and not is_supported_source_tree_filename(name)
        )

    def _require_readable_directory(self, path: Path) -> None:
        self._uow.release_before_io()
        if not self._filesystem.path_is_readable_directory(path):
            raise SourceScanStartUnavailableError

    def _prune_missing_children(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        seen_path_keys: set[str],
    ) -> None:
        if self._source_node_deletion is None:
            raise RuntimeError("source node deletion is not configured")
        with self._uow.transaction():
            stale_ids = tuple(
                child.id
                for child in self._source_nodes.list_direct_children(
                    library_id=library_id,
                    parent_id=parent_id,
                )
                if child.path_key not in seen_path_keys
            )
        for source_node_id in stale_ids:
            self._source_node_deletion.delete_source_node(source_node_id)

    def _persist_directory_decision(
        self,
        *,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        decision: DirectoryProbeDecision,
    ) -> bool:
        adapter = decision.adapter
        self._source_nodes.upsert_interpretation(
            source_node_id=node_id,
            result=decision.result.value,
            source="AUTO",
            adapter_id=adapter.adapter_id.value if adapter else None,
            adapter_version=adapter.adapter_version if adapter else None,
            reason_code=decision.reason_code,
            sample_relative_paths="\n".join(decision.evidence.sample_relative_paths)
            or None,
            sample_count=decision.evidence.sample_count,
            max_entries_visited=decision.evidence.entries_visited,
            max_depth=decision.evidence.max_depth_reached,
            time_budget_ms=config.probe_time_budget_ms,
            termination_reason=decision.evidence.termination_reason.value,
            recognized_at=self._clock.now(),
        )
        existing = self._books_resources.get_resource_by_source_node(node_id)
        if decision.result is not ProbeInterpretationResult.RESOURCE or adapter is None:
            if existing is not None:
                self._books_resources.delete_resource(existing.id)
            return existing is not None
        book_id = self._resolve_book_id(
            config, node_id, relative_path, is_directory=True
        )
        if book_id is None:
            if existing is not None:
                self._books_resources.delete_resource(existing.id)
            return existing is not None
        identity = adapter_identity(adapter)
        if existing is not None and existing.adapter_id != identity.adapter_id:
            self._books_resources.delete_resource(existing.id)
            existing = None
        if existing is not None:
            if (
                existing.adapter_id == identity.adapter_id
                and existing.adapter_version == identity.adapter_version
                and existing.format == identity.format_label
            ):
                return False
            self._books_resources.refresh_resource_adapter(
                resource_id=existing.id,
                adapter=identity,
            )
            return True
        self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=identity,
        )
        return True

    def _enqueue_directory_samples(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        decision: DirectoryProbeDecision,
    ) -> int:
        resource = self._books_resources.get_resource_by_source_node(node_id)
        adapter = decision.adapter
        if resource is None or adapter is None:
            return 0
        count = 0
        for sample in decision.evidence.sample_relative_paths:
            sample_path = SourceNodeRelativePath(sample)
            sample_node = self._source_nodes.get_by_path_key(
                config.library_id, sample_path.path_key
            )
            if sample_node is None:
                continue
            if file_extension(sample_path.name) in adapter.file_extensions:
                count += self._ensure_asset_for_resource(
                    config, resource.id, sample_node.id, sample_path.name
                )
        return count

    def _process_regular_file(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        *,
        observation_changed: bool,
    ) -> tuple[int, int]:
        owner = self._books_resources.find_outermost_directory_resource(
            config.library_id, relative_path.value
        )
        existing = self._books_resources.get_resource_by_source_node(node_id)
        if owner is not None:
            self._mark_node_covered_by_directory_resource(node_id)
            adapter = self._adapter_for_resource(owner, relative_path.name)
            if observation_changed and adapter is not None:
                self._requeue_asset_import(
                    config=config,
                    resource_id=owner.id,
                    source_node_id=node_id,
                    adapter=adapter,
                )
                return (0, 1)
            return (
                0,
                self._ensure_asset_for_resource(
                    config, owner.id, node_id, relative_path.name
                ),
            )

        matches = match_file_adapters(relative_path.name)
        adapter = unique_adapter_or_none(matches)
        if adapter is None:
            if existing is not None:
                self._books_resources.delete_resource(existing.id)
            self._source_nodes.upsert_interpretation(
                source_node_id=node_id,
                result="NODE_ONLY",
                source="AUTO",
                adapter_id=None,
                adapter_version=None,
                reason_code="NO_UNIQUE_ADAPTER",
                sample_relative_paths=None,
                sample_count=None,
                max_entries_visited=None,
                max_depth=None,
                time_budget_ms=None,
                termination_reason=None,
                recognized_at=self._clock.now(),
            )
            return (0, 0)

        identity = adapter_identity(adapter, source_name=relative_path.name)
        if existing is not None and existing.adapter_id != identity.adapter_id:
            self._books_resources.delete_resource(existing.id)
            existing = None
        if existing is not None:
            adapter_changed = (
                existing.adapter_id != identity.adapter_id
                or existing.adapter_version != identity.adapter_version
                or existing.format != identity.format_label
            )
            if adapter_changed:
                self._books_resources.refresh_resource_adapter(
                    resource_id=existing.id,
                    adapter=identity,
                )
            self._upsert_file_resource_interpretation(
                node_id=node_id,
                adapter=adapter,
                reason_code=(
                    "ADAPTER_CONTRACT_UPGRADED" if adapter_changed else "UNIQUE_ADAPTER"
                ),
            )
            if adapter_changed or observation_changed:
                self._requeue_asset_import(
                    config=config,
                    resource_id=existing.id,
                    source_node_id=node_id,
                    adapter=adapter,
                )
                return (int(adapter_changed), 1)
            return (
                0,
                self._ensure_asset_for_resource(
                    config, existing.id, node_id, relative_path.name
                ),
            )

        book_id = self._resolve_book_id(
            config, node_id, relative_path, is_directory=False
        )
        if book_id is None:
            return (0, 0)
        resource = self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=identity,
        )
        self._upsert_file_resource_interpretation(
            node_id=node_id,
            adapter=adapter,
            reason_code="UNIQUE_ADAPTER",
        )
        enqueued = self._ensure_asset_for_resource(
            config, resource.id, node_id, relative_path.name
        )
        return (1, enqueued)

    def _upsert_file_resource_interpretation(
        self,
        *,
        node_id: str,
        adapter: ResourceAdapterSpec,
        reason_code: str,
    ) -> None:
        self._source_nodes.upsert_interpretation(
            source_node_id=node_id,
            result="RESOURCE",
            source="AUTO",
            adapter_id=adapter.adapter_id.value,
            adapter_version=adapter.adapter_version,
            reason_code=reason_code,
            sample_relative_paths=None,
            sample_count=None,
            max_entries_visited=None,
            max_depth=None,
            time_budget_ms=None,
            termination_reason=None,
            recognized_at=self._clock.now(),
        )

    def _requeue_asset_import(
        self,
        *,
        config: LibrarySourceTreeConfig,
        resource_id: str,
        source_node_id: str,
        adapter: ResourceAdapterSpec,
    ) -> None:
        self._books_resources.invalidate_asset_for_reimport(
            resource_id=resource_id,
            source_node_id=source_node_id,
        )
        self._queue.requeue_import_asset_task(
            library_id=config.library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=adapter.asset_role,
        )

    @staticmethod
    def _adapter_for_resource(
        resource: ReadableResourceRecord,
        source_name: str,
    ) -> ResourceAdapterSpec | None:
        extension = file_extension(source_name)
        return next(
            (
                spec
                for spec in ADAPTER_SPECS
                if spec.adapter_id.value == resource.adapter_id
                and extension in spec.file_extensions
            ),
            None,
        )

    def _resolve_book_id(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        *,
        is_directory: bool,
    ) -> str | None:
        placement = decide_book_anchor_for_resource(
            organization_mode=config.organization_mode,
            resource_relative_path=relative_path,
            resource_is_directory=is_directory,
        )
        if placement.create_new_book_at_source_node:
            return self._books_resources.ensure_book(
                library_id=config.library_id,
                source_node_id=node_id,
                title=relative_path.name,
            )
        if placement.resource_root_folder_relative_path is None:
            return None
        root_path = SourceNodeRelativePath(placement.resource_root_folder_relative_path)
        root_node = self._source_nodes.get_by_path_key(
            config.library_id, root_path.path_key
        )
        if root_node is None:
            return None
        return self._books_resources.ensure_book(
            library_id=config.library_id,
            source_node_id=root_node.id,
            title=root_path.name,
        )

    def _ensure_asset_for_resource(
        self,
        config: LibrarySourceTreeConfig,
        resource_id: str,
        source_node_id: str,
        filename: str,
    ) -> int:
        resource = self._books_resources.get_resource(resource_id)
        if resource is None:
            return 0
        adapter = next(
            (
                spec
                for spec in ADAPTER_SPECS
                if spec.adapter_id.value == resource.adapter_id
            ),
            None,
        )
        if adapter is None or file_extension(filename) not in adapter.file_extensions:
            return 0
        role = adapter.asset_role
        task = self._queue.ensure_import_asset_task(
            library_id=config.library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=role,
        )
        return 0 if task is None else 1


__all__ = [
    "ScanLibrarySourceTree",
    "ScanLibrarySourceTreeResult",
    "SourceScanStartUnavailableError",
]
