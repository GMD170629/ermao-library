"""ScanLibrarySourceTree — ADR 0018 ordinary scan and first recognition."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    adapter_identity,
    BookResourceRepositoryPort,
    ClaimedWork,
    ClockPort,
    ImportRunRepositoryPort,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    PipelineLogPort,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
    WorkQueuePort,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeInterpretationResult,
)
from app.modules.imports.domain.import_run_policies import ImportRunKind
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    file_extension,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.library.domain.book_placement import (
    decide_book_anchor_for_resource,
    volumes_root_folder_creates_empty_book_on_discovery,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeViolationCode,
    evaluate_path_key_occupancy,
    parse_source_node_relative_path,
)

_SCAN_COMMIT_BATCH = 32
_DEFAULT_LEASE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class ScanLibrarySourceTreeResult:
    library_id: str
    nodes_inserted: int
    resources_created: int
    tasks_enqueued: int
    paused_for_backpressure: bool
    path_key_collisions: int
    stopped_for_lease: bool = False


class ScanLibrarySourceTree:
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

    def execute(
        self,
        library_id: str,
        claim: ClaimedWork | None = None,
        *,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    ) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            config = self._libraries.get_library(library_id)

        inserted = 0
        resources_created = 0
        tasks_enqueued = 0
        collisions = 0
        paused = False
        stopped_for_lease = False
        stack: list[tuple[str | None, str | None]] = [(None, None)]
        batch_writes = 0

        while stack:
            with self._uow.transaction():
                if claim is not None:
                    if not self._queue.fence_claim(claim, lease_seconds=lease_seconds):
                        stopped_for_lease = True
                        break
                queued = self._queue.queued_item_count()
            if queued >= config.queue_high_water:
                paused = True
                break

            parent_id, parent_rel = stack.pop()
            absolute = (
                config.root_path
                if parent_rel is None
                else self._filesystem.resolve_under_root(config.root_path, parent_rel)
            )
            self._uow.release_before_io()
            try:
                entries = self._filesystem.iter_directory_entries(absolute)
            except OSError:
                self._log.emit(
                    "source_tree.scan.directory_unreadable",
                    library_id=library_id,
                    stage="scan",
                    outcome="io_error",
                )
                continue

            directory_paused = False
            try:
                for name, kind, size, mtime_ns in entries:
                    if self._should_ignore(config, parent_rel, name):
                        continue
                    relative = name if parent_rel is None else f"{parent_rel}/{name}"
                    parsed = parse_source_node_relative_path(relative)
                    if not isinstance(parsed, SourceNodeRelativePath):
                        continue

                    if (
                        kind is SourceNodePhysicalKind.REGULAR_FILE
                        or kind is SourceNodePhysicalKind.DIRECTORY
                    ) and self._would_create_tasks(parsed, kind):
                        with self._uow.transaction():
                            if claim is not None and not self._queue.fence_claim(
                                claim, lease_seconds=lease_seconds
                            ):
                                stopped_for_lease = True
                                directory_paused = True
                                stack.append((parent_id, parent_rel))
                                break
                            if self._queue.queued_item_count() >= config.queue_high_water:
                                paused = True
                                directory_paused = True
                                stack.append((parent_id, parent_rel))
                                break

                    entry = ObservedSourceEntry(
                        relative_path=parsed,
                        physical_kind=kind,
                        observed_size_bytes=size,
                        observed_mtime_ns=mtime_ns,
                        observed_at=self._clock.now(),
                    )

                    with self._uow.transaction():
                        if claim is not None and not self._queue.fence_claim(
                            claim, lease_seconds=lease_seconds
                        ):
                            stopped_for_lease = True
                            directory_paused = True
                            stack.append((parent_id, parent_rel))
                            break
                        existing = self._source_nodes.get_by_path_key(
                            library_id, parsed.path_key
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
                                    library_id=library_id,
                                    stage="scan",
                                    outcome=SourceNodeViolationCode.PATH_KEY_COLLISION.value,
                                )
                                continue
                            node = existing
                            created = False
                        else:
                            node, created = self._source_nodes.insert_if_absent(
                                library_id=library_id,
                                parent_id=parent_id,
                                entry=entry,
                            )
                            if created:
                                inserted += 1
                                batch_writes += 1

                        if kind is SourceNodePhysicalKind.DIRECTORY:
                            if (
                                volumes_root_folder_creates_empty_book_on_discovery(
                                    config.organization_mode,
                                    is_root_child_directory=parsed.is_root_child,
                                )
                                and self._books_resources.get_book_id_for_source_node(
                                    node.id
                                )
                                is None
                            ):
                                self._books_resources.ensure_book(
                                    library_id=library_id,
                                    source_node_id=node.id,
                                    title=parsed.name,
                                )
                                batch_writes += 1
                            covered = (
                                self._books_resources.find_outermost_directory_resource(
                                    library_id, parsed.value
                                )
                            )
                            interpretation = self._source_nodes.get_interpretation(
                                node.id
                            )
                            needs_probe = interpretation is None and covered is None
                        else:
                            needs_probe = False
                            covered = None
                            interpretation = None

                    if stopped_for_lease:
                        break

                    if kind is SourceNodePhysicalKind.DIRECTORY:
                        if needs_probe:
                            self._uow.release_before_io()
                            decision, _termination = self._filesystem.probe_directory(
                                root=config.root_path,
                                directory_relative_path=parsed.value,
                                ignore_hidden=config.ignore_hidden,
                                ignore_patterns=config.ignore_patterns,
                                global_ignore_patterns=config.global_ignore_patterns,
                                sample_limit=config.probe_sample_limit,
                                max_entries=config.probe_max_entries,
                                max_depth=config.probe_max_depth,
                                time_budget_ms=config.probe_time_budget_ms,
                            )
                            with self._uow.transaction():
                                if claim is not None and not self._queue.fence_claim(
                                    claim, lease_seconds=lease_seconds
                                ):
                                    stopped_for_lease = True
                                    directory_paused = True
                                    stack.append((parent_id, parent_rel))
                                    break
                                if self._would_enqueue_from_decision(decision):
                                    if (
                                        self._queue.queued_item_count()
                                        >= config.queue_high_water
                                    ):
                                        paused = True
                                        directory_paused = True
                                        stack.append((parent_id, parent_rel))
                                        break
                                self._persist_directory_decision(
                                    config=config,
                                    node_id=node.id,
                                    relative_path=parsed,
                                    decision=decision,
                                )
                                if decision.result is ProbeInterpretationResult.RESOURCE:
                                    resources_created += 1
                                    tasks_enqueued += (
                                        self._enqueue_initial_directory_tasks(
                                            config, node.id, parsed, decision
                                        )
                                    )
                                batch_writes += 1
                        stack.append((node.id, parsed.value))
                        if batch_writes >= _SCAN_COMMIT_BATCH:
                            batch_writes = 0
                        continue

                    if kind is SourceNodePhysicalKind.REGULAR_FILE:
                        with self._uow.transaction():
                            if claim is not None and not self._queue.fence_claim(
                                claim, lease_seconds=lease_seconds
                            ):
                                stopped_for_lease = True
                                directory_paused = True
                                stack.append((parent_id, parent_rel))
                                break
                            interpretation = self._source_nodes.get_interpretation(
                                node.id
                            )
                            if interpretation is None:
                                if self._would_create_tasks(
                                    parsed, SourceNodePhysicalKind.REGULAR_FILE
                                ):
                                    if (
                                        self._queue.queued_item_count()
                                        >= config.queue_high_water
                                    ):
                                        paused = True
                                        directory_paused = True
                                        stack.append((parent_id, parent_rel))
                                        break
                                created_count, enqueued = self._recognize_regular_file(
                                    config, node.id, parsed
                                )
                                resources_created += created_count
                                tasks_enqueued += enqueued
                                batch_writes += 1
                            else:
                                owner = (
                                    self._books_resources.find_outermost_directory_resource(
                                        library_id, parsed.value
                                    )
                                )
                                if owner is not None:
                                    if (
                                        self._queue.queued_item_count()
                                        >= config.queue_high_water
                                    ):
                                        paused = True
                                        directory_paused = True
                                        stack.append((parent_id, parent_rel))
                                        break
                                    tasks_enqueued += self._enqueue_owned_or_incremental(
                                        config, owner.id, node.id, parsed.name
                                    )
                                    batch_writes += 1
            except OSError:
                self._log.emit(
                    "source_tree.scan.directory_unreadable",
                    library_id=library_id,
                    stage="scan",
                    outcome="io_error",
                )
                continue

            if directory_paused or stopped_for_lease:
                break

        outcome = "ok"
        if stopped_for_lease:
            outcome = "lease_lost"
        elif paused:
            outcome = "paused"
        self._log.emit(
            "source_tree.scan.completed",
            library_id=library_id,
            stage="scan",
            outcome=outcome,
        )
        return ScanLibrarySourceTreeResult(
            library_id=library_id,
            nodes_inserted=inserted,
            resources_created=resources_created,
            tasks_enqueued=tasks_enqueued,
            paused_for_backpressure=paused,
            path_key_collisions=collisions,
            stopped_for_lease=stopped_for_lease,
        )

    def _should_ignore(
        self,
        config: LibrarySourceTreeConfig,
        parent_rel: str | None,
        name: str,
    ) -> bool:
        if config.ignore_hidden and name.startswith(".") and name not in {".", ".."}:
            return True
        relative = name if parent_rel is None else f"{parent_rel}/{name}"
        for patterns in (config.global_ignore_patterns, config.ignore_patterns or ""):
            for pattern in patterns.splitlines():
                pattern = pattern.strip()
                if not pattern:
                    continue
                if pattern == name or pattern == relative or relative.endswith(
                    "/" + pattern
                ):
                    return True
        return False

    def _would_create_tasks(
        self,
        path: SourceNodeRelativePath,
        kind: SourceNodePhysicalKind,
    ) -> bool:
        if kind is SourceNodePhysicalKind.REGULAR_FILE:
            return unique_adapter_or_none(match_file_adapters(path.name)) is not None
        return True

    def _would_enqueue_from_decision(self, decision: DirectoryProbeDecision) -> bool:
        return decision.result is ProbeInterpretationResult.RESOURCE

    def _persist_directory_decision(
        self,
        *,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        decision: DirectoryProbeDecision,
    ) -> None:
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
        if (
            decision.result is not ProbeInterpretationResult.RESOURCE
            or adapter is None
        ):
            return
        placement = decide_book_anchor_for_resource(
            organization_mode=config.organization_mode,
            resource_relative_path=relative_path,
            resource_is_directory=True,
        )
        if placement.create_new_book_at_source_node:
            book_id = self._books_resources.ensure_book(
                library_id=config.library_id,
                source_node_id=node_id,
                title=relative_path.name,
            )
        else:
            if placement.volumes_root_folder_relative_path is None:
                return
            root_path = SourceNodeRelativePath(
                placement.volumes_root_folder_relative_path
            )
            root_node = self._source_nodes.get_by_path_key(
                config.library_id, root_path.path_key
            )
            if root_node is None:
                return
            book_id = self._books_resources.ensure_book(
                library_id=config.library_id,
                source_node_id=root_node.id,
                title=root_path.name,
            )
        run_id = self._import_runs.create_run(
            library_id=config.library_id,
            kind=ImportRunKind.INITIAL,
            source_node_id=node_id,
            resource_id=None,
            adapter_id=adapter.adapter_id.value,
            adapter_version=adapter.adapter_version,
        )
        resource = self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter_identity(adapter),
            active_import_run_id=run_id,
        )
        self._import_runs.attach_resource(run_id, resource.id)
        self._import_runs.upsert_resource_candidate(
            import_run_id=run_id,
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter,
            title=relative_path.name,
        )

    def _enqueue_initial_directory_tasks(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
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
                task = self._import_runs.create_task(
                    library_id=config.library_id,
                    resource_id=resource.id,
                    source_node_id=sample_node.id,
                    owner_import_run_id=resource.active_import_run_id,
                    role=adapter.asset_role,
                )
                self._queue.enqueue_library_import_task(task.id)
                count += 1
        if resource.active_import_run_id is not None:
            self._import_runs.mark_discovery_complete(resource.active_import_run_id)
        return count

    def _recognize_regular_file(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
    ) -> tuple[int, int]:
        # Outer directory resources (PAGE/TRACK) own compatible children even when
        # the filename has no standalone file adapter (e.g. .png under image-dir).
        owner = self._books_resources.find_outermost_directory_resource(
            config.library_id, relative_path.value
        )
        if owner is not None:
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
            return (
                0,
                self._enqueue_owned_or_incremental(
                    config, owner.id, node_id, relative_path.name
                ),
            )

        matches = match_file_adapters(relative_path.name)
        adapter = unique_adapter_or_none(matches)
        if adapter is None:
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

        placement = decide_book_anchor_for_resource(
            organization_mode=config.organization_mode,
            resource_relative_path=relative_path,
            resource_is_directory=False,
        )
        if placement.create_new_book_at_source_node:
            book_id = self._books_resources.ensure_book(
                library_id=config.library_id,
                source_node_id=node_id,
                title=relative_path.name,
            )
        else:
            if placement.volumes_root_folder_relative_path is None:
                return (0, 0)
            root_path = SourceNodeRelativePath(
                placement.volumes_root_folder_relative_path
            )
            root_node = self._source_nodes.get_by_path_key(
                config.library_id, root_path.path_key
            )
            if root_node is None:
                return (0, 0)
            book_id = self._books_resources.ensure_book(
                library_id=config.library_id,
                source_node_id=root_node.id,
                title=root_path.name,
            )
        run_id = self._import_runs.create_run(
            library_id=config.library_id,
            kind=ImportRunKind.INITIAL,
            source_node_id=node_id,
            resource_id=None,
            adapter_id=adapter.adapter_id.value,
            adapter_version=adapter.adapter_version,
        )
        resource = self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter_identity(adapter),
            active_import_run_id=run_id,
        )
        self._import_runs.attach_resource(run_id, resource.id)
        self._source_nodes.upsert_interpretation(
            source_node_id=node_id,
            result="RESOURCE",
            source="AUTO",
            adapter_id=adapter.adapter_id.value,
            adapter_version=adapter.adapter_version,
            reason_code="UNIQUE_ADAPTER",
            sample_relative_paths=None,
            sample_count=None,
            max_entries_visited=None,
            max_depth=None,
            time_budget_ms=None,
            termination_reason=None,
            recognized_at=self._clock.now(),
        )
        self._import_runs.upsert_resource_candidate(
            import_run_id=run_id,
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter,
            title=relative_path.name,
        )
        task = self._import_runs.create_task(
            library_id=config.library_id,
            resource_id=resource.id,
            source_node_id=node_id,
            owner_import_run_id=run_id,
            role=adapter.asset_role,
        )
        self._queue.enqueue_library_import_task(task.id)
        self._import_runs.mark_discovery_complete(run_id)
        return (1, 1)

    def _enqueue_owned_or_incremental(
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
        owner_run_id = resource.active_import_run_id
        task = self._import_runs.create_task(
            library_id=config.library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            owner_import_run_id=owner_run_id,
            role=adapter.asset_role,
        )
        self._queue.enqueue_library_import_task(task.id)
        return 1
