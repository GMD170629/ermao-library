"""Continue-import scan: streaming SourceNode discovery and task enqueue."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    adapter_identity,
    BookResourceRepositoryPort,
    ClockPort,
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


@dataclass(frozen=True, slots=True)
class ScanLibrarySourceTreeResult:
    library_id: str
    nodes_inserted: int
    resources_created: int
    tasks_enqueued: int
    path_key_collisions: int


class ScanLibrarySourceTree:
    """Execute SCAN_LIBRARY / CONTINUE_SOURCE work (single consumer, no lease)."""

    def __init__(
        self,
        *,
        libraries: LibraryConfigPort,
        filesystem: SourceTreeFilesystemPort,
        source_nodes: SourceNodeRepositoryPort,
        books_resources: BookResourceRepositoryPort,
        queue: WorkQueuePort,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        log: PipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._queue = queue
        self._uow = uow
        self._clock = clock
        self._log = log

    def execute_library(self, library_id: str) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            config = self._libraries.get_library(library_id)
        return self._walk(
            config=config,
            start_parent_id=None,
            start_parent_rel=None,
            reprobe_node_only=True,
        )

    def execute_source(self, source_node_id: str) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            node = self._source_nodes.get(source_node_id)
            if node is None:
                raise LookupError(source_node_id)
            config = self._libraries.get_library(node.library_id)
            relative = SourceNodeRelativePath(node.relative_path)

        if node.physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
            return self._continue_file(config, node.id, relative)
        if node.physical_kind is SourceNodePhysicalKind.DIRECTORY:
            # Re-probe NODE_ONLY / missing interpretation at this directory first.
            self._maybe_reprobe_directory(config, node.id, relative)
            return self._walk(
                config=config,
                start_parent_id=node.id,
                start_parent_rel=relative.value,
                reprobe_node_only=True,
            )
        return ScanLibrarySourceTreeResult(
            library_id=config.library_id,
            nodes_inserted=0,
            resources_created=0,
            tasks_enqueued=0,
            path_key_collisions=0,
        )

    def _continue_file(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative: SourceNodeRelativePath,
    ) -> ScanLibrarySourceTreeResult:
        resources = 0
        tasks = 0
        with self._uow.transaction():
            interpretation = self._source_nodes.get_interpretation(node_id)
            resource = self._books_resources.get_resource_by_source_node(node_id)
            if resource is not None:
                created, enqueued = 0, self._ensure_asset_for_resource(
                    config, resource.id, node_id, relative.name
                )
            elif interpretation is None or interpretation.result == "NODE_ONLY":
                created, enqueued = self._recognize_regular_file(
                    config, node_id, relative, force_reprobe=True
                )
            else:
                created, enqueued = 0, 0
            resources += created
            tasks += enqueued
        return ScanLibrarySourceTreeResult(
            library_id=config.library_id,
            nodes_inserted=0,
            resources_created=resources,
            tasks_enqueued=tasks,
            path_key_collisions=0,
        )

    def _walk(
        self,
        *,
        config: LibrarySourceTreeConfig,
        start_parent_id: str | None,
        start_parent_rel: str | None,
        reprobe_node_only: bool,
    ) -> ScanLibrarySourceTreeResult:
        inserted = 0
        resources_created = 0
        tasks_enqueued = 0
        collisions = 0
        stack: list[tuple[str | None, str | None]] = [
            (start_parent_id, start_parent_rel)
        ]

        while stack:
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
                continue

            while True:
                try:
                    name, kind, size, mtime_ns = next(directory_entries)
                except StopIteration:
                    break
                except OSError:
                    self._log.emit(
                        "source_tree.scan.directory_unreadable",
                        library_id=config.library_id,
                        stage="scan",
                        outcome="io_error",
                    )
                    break

                if self._should_ignore(config, parent_rel, name):
                    continue
                relative_str = name if parent_rel is None else f"{parent_rel}/{name}"
                parsed = parse_source_node_relative_path(relative_str)
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
                        node = existing
                    else:
                        node, created = self._source_nodes.insert_if_absent(
                            library_id=config.library_id,
                            parent_id=parent_id,
                            entry=entry,
                        )
                        if created:
                            inserted += 1

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
                                library_id=config.library_id,
                                source_node_id=node.id,
                                title=parsed.name,
                            )
                        covered = (
                            self._books_resources.find_outermost_directory_resource(
                                config.library_id, parsed.value
                            )
                        )
                        interpretation = self._source_nodes.get_interpretation(node.id)
                        needs_probe = covered is None and (
                            interpretation is None
                            or (
                                reprobe_node_only
                                and interpretation.result == "NODE_ONLY"
                            )
                        )
                    else:
                        needs_probe = False
                        covered = None
                        interpretation = self._source_nodes.get_interpretation(node.id)

                if kind is SourceNodePhysicalKind.DIRECTORY:
                    if needs_probe:
                        created_r, enqueued = self._probe_and_persist_directory(
                            config, node.id, parsed
                        )
                        resources_created += created_r
                        tasks_enqueued += enqueued
                    elif interpretation is not None and interpretation.result == "RESOURCE":
                        # Existing directory resource: ensure tasks for compatible children later
                        pass
                    stack.append((node.id, parsed.value))
                    continue

                if kind is SourceNodePhysicalKind.REGULAR_FILE:
                    with self._uow.transaction():
                        interpretation = self._source_nodes.get_interpretation(node.id)
                        resource = self._books_resources.get_resource_by_source_node(
                            node.id
                        )
                        owner = self._books_resources.find_outermost_directory_resource(
                            config.library_id, parsed.value
                        )
                        if resource is not None:
                            tasks_enqueued += self._ensure_asset_for_resource(
                                config, resource.id, node.id, parsed.name
                            )
                        elif owner is not None:
                            if interpretation is None:
                                self._source_nodes.upsert_interpretation(
                                    source_node_id=node.id,
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
                            tasks_enqueued += self._ensure_asset_for_resource(
                                config, owner.id, node.id, parsed.name
                            )
                        elif interpretation is None or (
                            reprobe_node_only and interpretation.result == "NODE_ONLY"
                        ):
                            created_r, enqueued = self._recognize_regular_file(
                                config,
                                node.id,
                                parsed,
                                force_reprobe=True,
                            )
                            resources_created += created_r
                            tasks_enqueued += enqueued

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

    def _maybe_reprobe_directory(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative: SourceNodeRelativePath,
    ) -> None:
        with self._uow.transaction():
            interpretation = self._source_nodes.get_interpretation(node_id)
            resource = self._books_resources.get_resource_by_source_node(node_id)
            if resource is not None:
                return
            if interpretation is not None and interpretation.result != "NODE_ONLY":
                return
        self._probe_and_persist_directory(config, node_id, relative)

    def _probe_and_persist_directory(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative: SourceNodeRelativePath,
    ) -> tuple[int, int]:
        self._uow.release_before_io()
        decision, _termination = self._filesystem.probe_directory(
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
            # Do not overwrite an existing RESOURCE interpretation/adapter.
            existing_resource = self._books_resources.get_resource_by_source_node(
                node_id
            )
            if existing_resource is not None:
                return (0, self._enqueue_directory_samples(config, node_id, decision))
            self._persist_directory_decision(
                config=config,
                node_id=node_id,
                relative_path=relative,
                decision=decision,
            )
            if decision.result is ProbeInterpretationResult.RESOURCE:
                return (
                    1,
                    self._enqueue_directory_samples(config, node_id, decision),
                )
        return (0, 0)

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
        if self._books_resources.get_resource_by_source_node(node_id) is not None:
            return
        book_id = self._resolve_book_id(config, node_id, relative_path, is_directory=True)
        if book_id is None:
            return
        self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter_identity(adapter),
        )

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

    def _recognize_regular_file(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        *,
        force_reprobe: bool,
    ) -> tuple[int, int]:
        del force_reprobe  # always allow on continue-import path
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
            return (0, self._ensure_asset_for_resource(
                config, owner.id, node_id, relative_path.name
            ))

        existing = self._books_resources.get_resource_by_source_node(node_id)
        if existing is not None:
            return (0, self._ensure_asset_for_resource(
                config, existing.id, node_id, relative_path.name
            ))

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

        book_id = self._resolve_book_id(
            config, node_id, relative_path, is_directory=False
        )
        if book_id is None:
            return (0, 0)
        resource = self._books_resources.create_pending_resource(
            library_id=config.library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter=adapter_identity(adapter),
        )
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
        enqueued = self._ensure_asset_for_resource(
            config, resource.id, node_id, relative_path.name
        )
        return (1, enqueued)

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
        if placement.volumes_root_folder_relative_path is None:
            return None
        root_path = SourceNodeRelativePath(placement.volumes_root_folder_relative_path)
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


__all__ = ["ScanLibrarySourceTree", "ScanLibrarySourceTreeResult"]
