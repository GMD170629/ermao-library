"""Directory-confirmed SourceNode reconciliation and import task enqueue."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.modules.imports.application.readable_resource.ports import (
    BookResourceRepositoryPort,
    ClockPort,
    DirectoryEntry,
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LibrarySourceTreeConfig,
    LocalCoverPublicationPort,
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
    ProbeTerminationReason,
)
from app.modules.imports.domain.ignore_rules import (
    is_builtin_ignored_file,
    should_ignore_source_entry,
)
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    ResourceAdapterSpec,
    file_extension,
    is_supported_source_tree_filename,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.imports.domain.scan_policy import (
    MissingEntryPolicy,
    ScanScope,
    merge_scan_scopes,
)
from app.modules.library.public import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeViolationCode,
    audiobook_resource_owns_path,
    decide_book_anchor_for_resource,
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


class SourceScanIncompleteError(SourceScanStartUnavailableError):
    code = "SOURCE_SCAN_INCOMPLETE"


class EmptyLibraryProtectedError(SourceScanStartUnavailableError):
    code = "EMPTY_LIBRARY_PROTECTED"


class SourceScanCancelledError(SourceScanStartUnavailableError):
    code = "SOURCE_SCAN_CANCELLED"


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
        covers: LocalCoverPublicationPort | None = None,
    ) -> None:
        self._covers = covers
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
        scan_scopes: tuple[ScanScope, ...] | None = None,
    ) -> ScanLibrarySourceTreeResult:
        with self._uow.transaction():
            config = self._libraries.get_library(library_id)
        self._require_readable_directory(config.root_path)
        if scan_scopes is not None:
            self._guard_empty_root(config)
            result = self._execute_scopes(config, scan_scopes, task_id=task_id)
        else:
            incomplete_paths: set[str] = set()
            try:
                result = self._walk(
                    config=config,
                    start_parent_id=None,
                    start_parent_rel=None,
                    task_id=task_id,
                    missing_entry_policy=missing_entry_policy,
                    incomplete_paths=incomplete_paths,
                )
            except Exception:
                # Every non-successful exit leaves the affected ranges gated;
                # only a later complete enumeration may release them.
                self._record_incomplete_scan(
                    task_id,
                    config.library_id,
                    self._paths_to_scopes(incomplete_paths, None),
                )
                raise
            self._clear_complete_scan(config.library_id, (ScanScope("", True),))
        self._log.emit(
            "source_tree.scan.completed",
            library_id=config.library_id,
            stage="scan",
            outcome="ok",
        )
        return result

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

        self._require_readable_directory(config.root_path)

        absolute = self._filesystem.resolve_under_root(config.root_path, relative.value)
        self._uow.release_before_io()
        file_observation: RegularFileObservation | None = None
        if node.physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
            file_observation = self._filesystem.observe_readable_file(absolute)
            if file_observation is None:
                raise SourceScanStartUnavailableError
        elif node.physical_kind is SourceNodePhysicalKind.DIRECTORY:
            self._require_readable_directory(absolute)
        self._guard_empty_root(config)

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
            incomplete_paths: set[str] = set()
            try:
                result = self._walk(
                    config=config,
                    start_parent_id=node.id,
                    start_parent_rel=relative.value,
                    task_id=task_id,
                    missing_entry_policy=missing_entry_policy,
                    incomplete_paths=incomplete_paths,
                )
            except Exception:
                self._record_incomplete_scan(
                    task_id,
                    config.library_id,
                    self._paths_to_scopes(
                        incomplete_paths, ScanScope(relative.value, True)
                    ),
                )
                raise
            self._clear_complete_scan(
                config.library_id, (ScanScope(relative.value, True),)
            )
            return result
        return ScanLibrarySourceTreeResult(
            library_id=config.library_id,
            nodes_inserted=0,
            resources_created=0,
            tasks_enqueued=0,
            path_key_collisions=0,
        )

    def _guard_empty_root(self, config: LibrarySourceTreeConfig) -> None:
        self._uow.release_before_io()
        try:
            entries = self._filesystem.iter_directory_entries(config.root_path)
            try:
                first = next(entries, None)
            finally:
                close = getattr(entries, "close", None)
                if close is not None:
                    close()
        except OSError as error:
            raise SourceScanStartUnavailableError() from error
        if isinstance(first, UnreadableDirectoryEntry):
            raise SourceScanStartUnavailableError()
        if first is None and not config.allow_empty_library_cleanup:
            with self._uow.transaction():
                if self._libraries.source_node_count(config.library_id):
                    raise EmptyLibraryProtectedError()

    def _execute_scopes(
        self,
        config: LibrarySourceTreeConfig,
        scopes: tuple[ScanScope, ...],
        *,
        task_id: str | None,
    ) -> ScanLibrarySourceTreeResult:
        expanded: tuple[ScanScope, ...] = ()
        for scope in scopes:
            path = scope.relative_path
            with self._uow.transaction():
                owner = self._books_resources.find_outermost_directory_resource(
                    config.library_id, path + "/__scan__" if path else "__scan__"
                )
                if owner is not None:
                    node = self._source_nodes.get(owner.source_node_id)
                    if node is not None:
                        scope = ScanScope(node.relative_path, True)
            expanded += (scope,)
        normalized = merge_scan_scopes((), expanded) or ()
        pending = list(normalized)
        visited: set[str] = set()
        totals = [0, 0, 0, 0]
        failed = False
        failed_error: BaseException | None = None
        completed_scopes: list[ScanScope] = []
        incomplete_scopes: list[ScanScope] = []
        while pending:
            if self._task_was_cancelled(task_id):
                # Cancellation stops the round; unprocessed ranges stay gated.
                incomplete_scopes.extend(pending)
                self._record_incomplete_scan(
                    task_id, config.library_id, tuple(incomplete_scopes)
                )
                raise SourceScanCancelledError()
            scope = pending.pop(0)
            relative = scope.relative_path
            with self._uow.transaction():
                node = (
                    self._source_nodes.get_by_path_key(
                        config.library_id, SourceNodeRelativePath(relative).path_key
                    )
                    if relative
                    else None
                )
            if relative and node is None:
                parent = relative.rpartition("/")[0]
                if parent not in visited:
                    pending[0:0] = [ScanScope(parent), scope]
                    continue
                # A successfully scanned parent did not discover this path.
                # Remember its absence so descendant events cannot repeatedly
                # schedule this already resolved parent after a directory move.
                visited.add(relative)
                continue
            if (
                node is not None
                and node.physical_kind is not SourceNodePhysicalKind.DIRECTORY
            ):
                continue
            if relative:
                self._uow.release_before_io()
                absolute = self._filesystem.resolve_under_root(
                    config.root_path, relative
                )
                if not self._filesystem.path_is_readable_directory(absolute):
                    try:
                        parent = self._confirmed_missing_parent(config, relative)
                        pending.insert(0, ScanScope(parent))
                    except SourceScanIncompleteError as error:
                        failed = True
                        failed_error = failed_error or error
                        incomplete_scopes.append(scope)
                    continue
            visited.add(relative)
            failed_paths: set[str] = set()
            try:
                result = self._walk(
                    config=config,
                    start_parent_id=node.id if node else None,
                    start_parent_rel=relative or None,
                    task_id=task_id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    recursive=scope.recursive,
                    incomplete_paths=failed_paths,
                )
                for index, value in enumerate(
                    (
                        result.nodes_inserted,
                        result.resources_created,
                        result.tasks_enqueued,
                        result.path_key_collisions,
                    )
                ):
                    totals[index] += value
            except SourceScanIncompleteError as error:
                failed = True
                failed_error = failed_error or error
                # The walk reports exact failed sub-ranges; never widen them
                # back into the whole requested parent scope.
                incomplete_scopes.extend(
                    self._paths_to_scopes(failed_paths, scope)
                )
            except Exception:
                # Preserve the current failure plus everything not yet visited.
                incomplete_scopes.extend(
                    self._paths_to_scopes(failed_paths, scope)
                )
                incomplete_scopes.extend(pending)
                self._record_incomplete_scan(
                    task_id, config.library_id, tuple(incomplete_scopes)
                )
                raise
            else:
                completed_scopes.append(scope)
        if completed_scopes:
            self._clear_complete_scan(config.library_id, tuple(completed_scopes))
        if failed:
            self._record_incomplete_scan(
                task_id, config.library_id, tuple(incomplete_scopes)
            )
            raise SourceScanIncompleteError() from failed_error
        return ScanLibrarySourceTreeResult(config.library_id, *totals)

    @staticmethod
    def _paths_to_scopes(
        paths: set[str], fallback: ScanScope | None
    ) -> tuple[ScanScope, ...]:
        scopes = tuple(ScanScope(path, True) for path in sorted(paths))
        if scopes or fallback is None:
            return scopes
        return (fallback,)

    def _record_incomplete_scan(
        self,
        task_id: str | None,
        library_id: str,
        scopes: tuple[ScanScope, ...],
    ) -> None:
        if not scopes:
            return
        with self._uow.transaction():
            self._queue.record_incomplete_scan(task_id, library_id, scopes)

    def _clear_complete_scan(
        self, library_id: str, scopes: tuple[ScanScope, ...]
    ) -> None:
        if not scopes or not self._queue.has_incomplete_ranges(library_id):
            return
        with self._uow.transaction():
            self._queue.clear_complete_scan(library_id, scopes)

    def _confirmed_missing_parent(
        self, config: LibrarySourceTreeConfig, relative: str
    ) -> str:
        """Only a complete parent listing can distinguish deletion from access failure."""
        candidate = relative
        while candidate:
            parent, _, name = candidate.rpartition("/")
            absolute = (
                self._filesystem.resolve_under_root(config.root_path, parent)
                if parent
                else config.root_path
            )
            self._uow.release_before_io()
            try:
                entries = list(self._filesystem.iter_directory_entries(absolute))
            except FileNotFoundError as error:
                if not parent:
                    raise SourceScanIncompleteError() from error
                candidate = parent
                continue
            except OSError as error:
                raise SourceScanIncompleteError() from error
            if any(isinstance(entry, UnreadableDirectoryEntry) for entry in entries):
                raise SourceScanIncompleteError()
            if any(
                entry[0] == name
                for entry in entries
                if not isinstance(entry, UnreadableDirectoryEntry)
            ):
                raise SourceScanIncompleteError()
            return parent
        raise SourceScanIncompleteError()

    def _walk(
        self,
        *,
        config: LibrarySourceTreeConfig,
        start_parent_id: str | None,
        start_parent_rel: str | None,
        task_id: str | None,
        missing_entry_policy: MissingEntryPolicy,
        recursive: bool = True,
        incomplete_paths: set[str] | None = None,
    ) -> ScanLibrarySourceTreeResult:
        inserted = 0
        resources_created = 0
        tasks_enqueued = 0
        collisions = 0
        failed = False
        failed_error: BaseException | None = None
        with self._uow.transaction():
            initial_owner = self._books_resources.find_outermost_directory_resource(
                config.library_id, start_parent_rel or "__root__"
            )
            initial_anchor = (
                self._source_nodes.get(initial_owner.source_node_id)
                if initial_owner
                else None
            )
        owner_anchors = (
            {initial_owner.id: initial_anchor.relative_path}
            if initial_owner and initial_anchor
            else {}
        )
        stack = [(start_parent_id, start_parent_rel, initial_owner)]
        listings: dict[str, tuple[DirectoryEntry, ...]] = {}
        current_rel: str | None = start_parent_rel
        try:
            while stack:
                if self._task_was_cancelled(task_id):
                    raise SourceScanCancelledError()
                parent_id, parent_rel, owner = stack.pop()
                current_rel = parent_rel
                absolute = (
                    config.root_path
                    if parent_rel is None
                    else self._filesystem.resolve_under_root(config.root_path, parent_rel)
                )
                self._uow.release_before_io()
                try:
                    observations = listings.pop(parent_rel or "", None)
                    if observations is None:
                        collected = []
                        for item in self._filesystem.iter_directory_entries(absolute):
                            if isinstance(item, UnreadableDirectoryEntry):
                                raise OSError("directory entry unavailable")
                            collected.append(item)
                        observations = tuple(collected)
                except OSError as error:
                    self._log.emit(
                        "source_tree.scan.directory_unreadable",
                        library_id=config.library_id,
                        stage="scan",
                        outcome="io_error",
                    )
                    failed = True
                    failed_error = failed_error or error
                    if incomplete_paths is not None:
                        incomplete_paths.add(parent_rel or "")
                    continue
                if (
                    parent_rel is None
                    and not observations
                    and not config.allow_empty_library_cleanup
                ):
                    with self._uow.transaction():
                        if self._libraries.source_node_count(config.library_id):
                            raise EmptyLibraryProtectedError()
                ownership_changed = False
                if parent_id is not None and parent_rel is not None:
                    try:
                        if owner is None:
                            created_r, enqueued = self._probe_and_persist_directory(
                                config,
                                parent_id,
                                SourceNodeRelativePath(parent_rel),
                                task_id=task_id,
                                observations=observations,
                                listings=listings,
                            )
                            resources_created += created_r
                            ownership_changed = bool(created_r)
                            tasks_enqueued += enqueued
                            with self._uow.transaction():
                                owner = self._books_resources.get_resource_by_source_node(
                                    parent_id
                                )
                        else:
                            with self._uow.transaction():
                                self._mark_node_covered_by_directory_resource(parent_id)
                    except SourceScanIncompleteError as error:
                        failed = True
                        failed_error = failed_error or error
                        if incomplete_paths is not None:
                            incomplete_paths.add(parent_rel or "")
                        continue
                if owner is not None:
                    owner_anchors.setdefault(owner.id, parent_rel)
                # Includes non-asset sidecars without making them SourceNodes or resources.
                context_version = hashlib.sha256(
                    json.dumps(
                        [
                            config.metadata_priority,
                            config.ignore_hidden,
                            config.ignore_patterns,
                            config.global_ignore_patterns,
                            self._filesystem.metadata_input_observations(
                                absolute, directory=True
                            )
                            if owner is not None and owner.source_node_id == parent_id
                            else (),
                            sorted(
                                (name, size, mtime)
                                for name, kind, size, mtime in observations
                                if kind is SourceNodePhysicalKind.REGULAR_FILE
                                and is_builtin_ignored_file(name)
                            ),
                        ],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                # Only the anchor owns directory metadata; child listings still contribute
                # member changes through the same durable resource task.
                if owner is not None and owner.source_node_id == parent_id:
                    with self._uow.transaction():
                        cover = self._books_resources.resource_cover_state(owner.id)
                    self._uow.release_before_io()
                    missing_cover = bool(
                        self._covers is not None
                        and cover.path
                        and not cover.protected
                        and not self._covers.exists(cover.path)
                    )
                    with self._uow.transaction():
                        changed = (
                            self._books_resources.refresh_scan_context(
                                owner.id, context_version
                            )
                            or missing_cover
                        )
                        # Unchanged inputs can still have failed or interrupted work.
                        # The queue reuses that task and skips unchanged successes.
                        task = self._queue.request_import_resource(
                            library_id=config.library_id,
                            resource_id=owner.id,
                            source_node_id=owner.source_node_id,
                            changed=changed,
                        )
                        tasks_enqueued += int(task is not None)
                seen_path_keys: set[str] = set()
                entries = []
                for name, kind, size, mtime in observations:
                    if self._should_ignore(config, parent_rel, name, kind):
                        continue
                    relative = parse_source_node_relative_path(
                        name if parent_rel is None else f"{parent_rel}/{name}"
                    )
                    if not isinstance(relative, SourceNodeRelativePath):
                        continue
                    seen_path_keys.add(relative.path_key)
                    entries.append(
                        ObservedSourceEntry(relative, kind, size, mtime, self._clock.now())
                    )
                for offset in range(0, len(entries), 200):
                    batch = tuple(entries[offset : offset + 200])
                    self._uow.release_before_io()
                    file_contexts = (
                        {}
                        if owner is not None
                        else {
                            entry.relative_path.value: hashlib.sha256(
                                json.dumps(
                                    [
                                        config.metadata_priority,
                                        self._filesystem.metadata_input_observations(
                                            self._filesystem.resolve_under_root(
                                                config.root_path, entry.relative_path.value
                                            ),
                                            directory=False,
                                        ),
                                    ]
                                ).encode()
                            ).hexdigest()
                            for entry in batch
                            if entry.physical_kind is SourceNodePhysicalKind.REGULAR_FILE
                        }
                    )
                    with self._uow.transaction():
                        if self._task_was_cancelled_in_transaction(task_id):
                            raise SourceScanCancelledError()
                        results = self._source_nodes.reconcile_batch(
                            library_id=config.library_id, parent_id=parent_id, entries=batch
                        )
                        affected = False
                        covered_ids = []
                        for entry, (node, created, changed) in zip(
                            batch, results, strict=True
                        ):
                            if node.relative_path != entry.relative_path.value:
                                collisions += 1
                                self._log.emit(
                                    "source_tree.scan.path_key_collision",
                                    library_id=config.library_id,
                                    stage="scan",
                                    outcome=SourceNodeViolationCode.PATH_KEY_COLLISION.value,
                                )
                                continue
                            inserted += int(created)
                            if entry.physical_kind is SourceNodePhysicalKind.DIRECTORY:
                                if (
                                    resource_root_folder_creates_empty_book_on_discovery(
                                        config.organization_mode,
                                        is_root_child_directory=entry.relative_path.is_root_child,
                                    )
                                    and self._books_resources.get_book_id_for_source_node(
                                        node.id
                                    )
                                    is None
                                ):
                                    self._books_resources.ensure_book(
                                        library_id=config.library_id,
                                        source_node_id=node.id,
                                        title=node.name,
                                    )
                                if recursive:
                                    stack.append(
                                        (
                                            node.id,
                                            node.relative_path,
                                            owner
                                            if owner is not None
                                            and (
                                                owner.format != "AUDIOBOOK_DIR"
                                                or audiobook_resource_owns_path(
                                                    resource_anchor=SourceNodeRelativePath(
                                                        owner_anchors[owner.id]
                                                    ),
                                                    candidate_path=entry.relative_path,
                                                    candidate_kind=entry.physical_kind,
                                                )
                                            )
                                            else None,
                                        )
                                    )
                            elif entry.physical_kind is SourceNodePhysicalKind.REGULAR_FILE:
                                if owner is not None:
                                    if changed or ownership_changed:
                                        covered_ids.append(node.id)
                                    affected |= changed
                                else:
                                    created_r, enqueued = self._process_regular_file(
                                        config,
                                        node.id,
                                        entry.relative_path,
                                        observation_changed=changed,
                                        owner_known=True,
                                        context_version=file_contexts[
                                            entry.relative_path.value
                                        ],
                                    )
                                    resources_created += created_r
                                    tasks_enqueued += enqueued
                        if covered_ids:
                            self._source_nodes.mark_covered_batch(
                                tuple(covered_ids), recognized_at=self._clock.now()
                            )
                        if affected and owner is not None:
                            self._queue.request_import_resource(
                                library_id=config.library_id,
                                resource_id=owner.id,
                                source_node_id=owner.source_node_id,
                                changed=True,
                            )
                            tasks_enqueued += 1
                if self._task_was_cancelled(task_id):
                    raise SourceScanCancelledError()
                if missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING:
                    self._prune_missing_children(
                        library_id=config.library_id,
                        parent_id=parent_id,
                        seen_path_keys=seen_path_keys,
                        owner=owner,
                    )

        except Exception:
            if incomplete_paths is not None:
                incomplete_paths.add(current_rel or "")
                for _, rel, _ in stack:
                    incomplete_paths.add(rel or "")
            raise
        if failed:
            raise SourceScanIncompleteError() from failed_error
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
        observations: tuple[DirectoryEntry, ...],
        listings: dict[str, tuple[DirectoryEntry, ...]],
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
            observations=observations,
            listings=listings,
        )
        if (
            decision.evidence.termination_reason
            is ProbeTerminationReason.LOCAL_IO_ERROR
        ):
            raise SourceScanIncompleteError()
        with self._uow.transaction():
            if self._task_was_cancelled_in_transaction(task_id):
                raise SourceScanCancelledError()
            changed = self._persist_directory_decision(
                config=config,
                node_id=node_id,
                relative_path=relative,
                decision=decision,
            )
            if decision.result is ProbeInterpretationResult.RESOURCE and changed:
                resource = self._books_resources.get_resource_by_source_node(node_id)
                if resource is not None:
                    self._queue.request_import_resource(
                        library_id=config.library_id,
                        resource_id=resource.id,
                        source_node_id=resource.source_node_id,
                        changed=True,
                    )
                    return (1, 1)
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
        owner: ReadableResourceRecord | None = None,
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
            if stale_ids and owner is not None:
                # Commit intent before the existing bounded deletion use case starts.
                self._queue.request_import_resource(
                    library_id=library_id,
                    resource_id=owner.id,
                    source_node_id=owner.source_node_id,
                    changed=True,
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

    def _process_regular_file(
        self,
        config: LibrarySourceTreeConfig,
        node_id: str,
        relative_path: SourceNodeRelativePath,
        *,
        observation_changed: bool,
        owner_known: bool = False,
        context_version: str | None = None,
    ) -> tuple[int, int]:
        owner = (
            None
            if owner_known
            else self._books_resources.find_outermost_directory_resource(
                config.library_id, relative_path.value
            )
        )
        existing = self._books_resources.get_resource_by_source_node(node_id)
        if owner is not None:
            self._mark_node_covered_by_directory_resource(node_id)
            if owner.format in {"IMAGE_DIR", "AUDIOBOOK_DIR"}:
                if observation_changed:
                    self._queue.request_import_resource(
                        library_id=config.library_id,
                        resource_id=owner.id,
                        source_node_id=owner.source_node_id,
                        changed=True,
                    )
                    return (0, 1)
                return (0, 0)
            return (0, 0)

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
            context_changed = (
                context_version is not None
                and self._books_resources.refresh_scan_context(
                    existing.id, context_version
                )
            )
            if context_changed and not (adapter_changed or observation_changed):
                self._queue.request_import_resource(
                    library_id=config.library_id,
                    resource_id=existing.id,
                    source_node_id=existing.source_node_id,
                    changed=True,
                )
                return (0, 1)
            if adapter_changed or observation_changed:
                self._requeue_resource_import(
                    config=config,
                    resource_id=existing.id,
                    source_node_id=node_id,
                    adapter=adapter,
                )
                return (int(adapter_changed), 1)
            return (
                0,
                self._ensure_resource_import(config, existing.id, relative_path.name),
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
        if context_version is not None:
            self._books_resources.refresh_scan_context(resource.id, context_version)
        self._upsert_file_resource_interpretation(
            node_id=node_id,
            adapter=adapter,
            reason_code="UNIQUE_ADAPTER",
        )
        enqueued = self._ensure_resource_import(config, resource.id, relative_path.name)
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

    def _requeue_resource_import(
        self,
        *,
        config: LibrarySourceTreeConfig,
        resource_id: str,
        source_node_id: str,
        adapter: ResourceAdapterSpec,
    ) -> None:
        if adapter.format_label in {"IMAGE_DIR", "AUDIOBOOK_DIR"}:
            return
        self._books_resources.invalidate_asset_for_reimport(
            resource_id=resource_id,
            source_node_id=source_node_id,
        )
        self._queue.request_import_resource(
            library_id=config.library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            changed=True,
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

    def _ensure_resource_import(
        self,
        config: LibrarySourceTreeConfig,
        resource_id: str,
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
        task = self._queue.request_import_resource(
            library_id=config.library_id,
            resource_id=resource_id,
            source_node_id=resource.source_node_id,
        )
        return 0 if task is None else 1


__all__ = [
    "ScanLibrarySourceTree",
    "ScanLibrarySourceTreeResult",
    "SourceScanStartUnavailableError",
]
