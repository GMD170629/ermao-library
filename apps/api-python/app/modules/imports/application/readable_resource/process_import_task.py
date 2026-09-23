"""Process resource tasks through shared file operations."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.local_metadata_snapshot import (
    LocalMetadataObservation,
    merge_observations,
)
from app.modules.imports.application.readable_resource.ports import (
    BookResourceRepositoryPort,
    ClockPort,
    FileParseResult,
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LocalCoverPublicationPort,
    LocalMetadataPriorityPort,
    PipelineLogPort,
    PreparedLocalCover,
    ReadableResourceRecord,
    RegularFileObservation,
    ResourceAdapterExecutorPort,
    SidecarWritebackPort,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
)
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    ResourceAdapterSpec,
)
from app.modules.library.public import (
    AssetImportState,
    AssetRole,
    DirectoryAssetResult,
    DirectoryImportMember,
    DirectoryMemberPage,
    ResourceAssetMetadataInput,
    SourceNodePhysicalKind,
)
from app.modules.media.public import FirstPageCoverPort
from app.modules.metadata.public import (
    LocalMetadataCandidate,
    ResolvedLocalMetadata,
    resolve_local_metadata,
)


class ImportTaskRuleError(Exception):
    """An observed import precondition/result fails without a lower exception."""


@dataclass(frozen=True, slots=True)
class ProcessTaskResult:
    task_id: str
    outcome: str


class ResourceImportRunPort(Protocol):
    """The caller owns the run's currency, follow-up request, and task state.

    ``is_current`` is called inside each result transaction. A Book owner must
    compare its claimed execution version there, not only task existence.
    """

    @property
    def operation_id(self) -> str: ...

    def is_current(self) -> bool: ...

    def directory_cursor(self, resource_id: str) -> str | None: ...

    def advance_directory_cursor(self, resource_id: str, member_id: str) -> None: ...

    def directory_cover_cursor(self, resource_id: str) -> str | None: ...

    def advance_directory_cover_cursor(self, resource_id: str, asset_id: str) -> None: ...

    @property
    def can_yield_directory(self) -> bool: ...

    def start(self, *, started_at: datetime) -> None: ...

    def request_changed(
        self, *, library_id: str, resource_id: str, source_node_id: str
    ) -> None: ...

    def succeed(self, *, finished_at: datetime) -> None: ...

    def fail(
        self, *, error_summary: str, finished_at: datetime,
        result_persisted: bool = False,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _QueuedResourceImportRun:
    """Translate the old resource task into the resource step's run boundary."""

    queue: LibraryImportTaskQueuePort
    operation_id: str

    @property
    def can_yield_directory(self) -> bool:
        return False

    def directory_cursor(self, resource_id: str) -> str | None:
        return None

    def advance_directory_cursor(self, resource_id: str, member_id: str) -> None:
        return None

    def directory_cover_cursor(self, resource_id: str) -> str | None:
        return None

    def advance_directory_cover_cursor(self, resource_id: str, asset_id: str) -> None:
        return None

    def is_current(self) -> bool:
        return self.queue.get_task(self.operation_id) is not None

    def start(self, *, started_at: datetime) -> None:
        task = self.queue.get_task(self.operation_id)
        if task is None:
            raise LookupError(self.operation_id)
        if task.state != "RUNNING":
            self.queue.mark_running(self.operation_id, started_at=started_at)

    def request_changed(
        self, *, library_id: str, resource_id: str, source_node_id: str
    ) -> None:
        self.queue.request_import_resource(
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            changed=True,
        )

    def succeed(self, *, finished_at: datetime) -> None:
        self.queue.mark_succeeded(self.operation_id, finished_at=finished_at)

    def fail(
        self, *, error_summary: str, finished_at: datetime,
        result_persisted: bool = False,
    ) -> None:
        self.queue.mark_failed(
            self.operation_id, error_summary=error_summary, finished_at=finished_at
        )


@dataclass(frozen=True, slots=True)
class ResourceImportContext:
    resource: ReadableResourceRecord
    node: SourceNodeRecord
    resource_node: SourceNodeRecord
    root_path: Path
    adapter: ResourceAdapterSpec | None
    local_metadata_priority: tuple[LocalMetadataSource, ...]


@dataclass(frozen=True, slots=True)
class PreparedResourceCovers:
    selected: PreparedLocalCover | None
    candidates: dict[LocalMetadataSource, PreparedLocalCover]
    publications: tuple[PreparedLocalCover, ...]


class ProcessReadableResourceImportTask:
    def __init__(
        self,
        *,
        libraries: LibraryConfigPort,
        filesystem: SourceTreeFilesystemPort,
        source_nodes: SourceNodeRepositoryPort,
        books_resources: BookResourceRepositoryPort,
        adapters: ResourceAdapterExecutorPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        log: PipelineLogPort,
        sidecar: SidecarWritebackPort,
        metadata_priority: LocalMetadataPriorityPort | None = None,
        covers: LocalCoverPublicationPort | None = None,
        first_page_covers: FirstPageCoverPort | None = None,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._adapters = adapters
        self._queue = queue
        self._uow = uow
        self._clock = clock
        self._log = log
        self._sidecar = sidecar
        self._metadata_priority = metadata_priority
        self._covers = covers
        self._first_page_covers = first_page_covers

    def reset_inspection_cache(self) -> None:
        self._adapters.reset_inspection_cache()

    def execute(self, task_id: str) -> ProcessTaskResult:
        with self._uow.transaction():
            task = self._queue.get_task(task_id)
            if task is None or task.kind != "IMPORT_RESOURCE":
                return ProcessTaskResult(task_id=task_id, outcome="missing_task")
            if task.resource_id is None or task.source_node_id is None:
                self._log.emit(
                    "readable_resource.task.rejected",
                    error=ImportTaskRuleError(
                        "Task is missing its required resource_id or source_node_id"
                    ),
                    task_id=task_id,
                    stage="import",
                    step="validate_task_shape",
                    outcome="failed",
                )
                self._queue.mark_failed(
                    task_id,
                    error_summary="INVALID_TASK_SHAPE",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="invalid_task")
            library_id = task.library_id
            resource_id = task.resource_id
            source_node_id = task.source_node_id
            run = _QueuedResourceImportRun(self._queue, task_id)
            prepared = self._prepare_resource(
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                run=run,
            )
        return (
            prepared
            if isinstance(prepared, ProcessTaskResult)
            else self._process_prepared_resource(prepared, run=run)
        )

    def process_resource(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        run: ResourceImportRunPort,
    ) -> ProcessTaskResult:
        """Process one resource without requiring an IMPORT_RESOURCE task row.

        The run owner checks cancellation/version and records follow-up or final
        state in the same transactions as the corresponding resource results.
        """
        with self._uow.transaction():
            prepared = self._prepare_resource(
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                run=run,
            )
        return (
            prepared
            if isinstance(prepared, ProcessTaskResult)
            else self._process_prepared_resource(prepared, run=run)
        )

    def _prepare_resource(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        run: ResourceImportRunPort,
    ) -> ResourceImportContext | ProcessTaskResult:
        task_id = run.operation_id
        if not run.is_current():
            return ProcessTaskResult(task_id=task_id, outcome="cancelled")
        context = self.load_resource_context(
            resource_id=resource_id, source_node_id=source_node_id
        )
        if context is None:
            self._log.emit(
                "readable_resource.task.rejected",
                error=ImportTaskRuleError(
                    "Task resource or source node could not be loaded"
                ),
                task_id=task_id,
                stage="import",
                step="load_task_targets",
                outcome="failed",
            )
            run.fail(error_summary="MISSING_TARGETS", finished_at=self._clock.now())
            return ProcessTaskResult(task_id=task_id, outcome="missing_targets")
        adapter = context.adapter
        if adapter is None:
            self._log.emit(
                "readable_resource.task.rejected",
                error=ImportTaskRuleError(
                    "No registered adapter matches the resource adapter identity"
                ),
                task_id=task_id,
                stage="import",
                step="select_resource_adapter",
                outcome="failed",
            )
            run.fail(error_summary="UNKNOWN_ADAPTER", finished_at=self._clock.now())
            return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")
        resource_is_directory = context.resource.format in {
            "IMAGE_DIR",
            "AUDIOBOOK_DIR",
        }
        if (
            (adapter.is_directory_adapter and not resource_is_directory)
            or context.node.id != context.resource.source_node_id
            or context.node.physical_kind
            is not (
                SourceNodePhysicalKind.DIRECTORY
                if resource_is_directory
                else SourceNodePhysicalKind.REGULAR_FILE
            )
            or context.resource.library_id != library_id
        ):
            self._log.emit(
                "readable_resource.task.rejected",
                error=ImportTaskRuleError(
                    "Resource task adapter kind, physical node kind, resource ownership or library does not match the queued target"
                ),
                task_id=task_id,
                stage="import",
                step="validate_task_target",
                outcome="failed",
            )
            run.fail(
                error_summary="INVALID_RESOURCE_TASK_TARGET",
                finished_at=self._clock.now(),
            )
            return ProcessTaskResult(task_id=task_id, outcome="invalid_task")
        run.start(started_at=self._clock.now())
        return context

    def _process_prepared_resource(
        self, context: ResourceImportContext, *, run: ResourceImportRunPort
    ) -> ProcessTaskResult:
        task_id = run.operation_id
        resource_id = context.resource.id
        library_id = context.resource.library_id
        source_node_id = context.node.id
        node = context.node
        relative_path = node.relative_path
        resource_relative_path = context.resource_node.relative_path
        root_path = context.root_path
        adapter = context.adapter
        assert adapter is not None
        role = adapter.asset_role
        assert role is not None
        local_metadata_priority = context.local_metadata_priority
        resource_is_directory = context.resource.format in {
            "IMAGE_DIR",
            "AUDIOBOOK_DIR",
        }
        if resource_is_directory:
            return self._execute_directory(task_id, context, run=run)
        self._uow.release_before_io()
        absolute = self._filesystem.resolve_under_root(root_path, relative_path)
        resource_absolute = self._filesystem.resolve_under_root(
            root_path, resource_relative_path
        )
        observation = self._filesystem.observe_readable_file(absolute)
        processed_version = self._processed_version(context, observation)
        if processed_version is not None:
            already_processed = self._books_resources.asset_has_processed_version(
                resource_id=resource_id,
                source_node_id=source_node_id,
                version=processed_version,
            )
            self._uow.release_before_io()
            if already_processed:
                return self._refresh_single_file_metadata(
                    task_id, context, resource_absolute, run=run
                )
        parsed = self._adapters.parse_file(
            absolute_path=absolute,
            resource_absolute_path=resource_absolute,
            adapter=adapter,
            role=role,
            local_metadata_priority=local_metadata_priority,
        )
        resource_metadata = (
            self._adapters.inspect_resource_metadata(
                resource_absolute_path=resource_absolute,
                adapter=adapter,
                local_metadata_priority=local_metadata_priority,
            )
            if parsed.ok and adapter.is_directory_adapter
            else None
        )
        local_metadata = (
            resolve_local_metadata(
                resource_metadata.candidates
                + (parsed.local_metadata.candidates if parsed.local_metadata else ()),
                local_metadata_priority,
            )
            if resource_metadata is not None
            else parsed.local_metadata
        )
        covers = self.prepare_resource_covers(
            context=context,
            parsed=parsed,
            local_metadata=local_metadata,
            absolute=absolute,
            task_id=task_id,
        )
        prepared_cover = covers.selected
        prepared_covers = covers.candidates
        publications = covers.publications

        # Publish new immutable versions before exposing their database references.
        # Failure or cancellation can discard them without touching existing covers.
        if self._covers is not None:
            try:
                for prepared in publications:
                    self._covers.publish(prepared)
            except OSError as error:
                self._log.emit(
                    "readable_resource.cover_publish_failed",
                    error=error,
                    stage="cover_publish",
                    outcome="COVER_PUBLISH_FAILED",
                    task_id=task_id,
                    resource_id=resource_id,
                    source_node_id=source_node_id,
                )
                for prepared in publications:
                    self._covers.discard(prepared)
                with self._uow.transaction():
                    if not run.is_current():
                        return ProcessTaskResult(task_id=task_id, outcome="cancelled")
                    run.fail(
                        error_summary="COVER_PUBLISH_FAILED",
                        finished_at=self._clock.now(),
                    )
                return ProcessTaskResult(task_id=task_id, outcome="failed")

        current_observation = self._filesystem.observe_readable_file(absolute)
        import_succeeded = False
        outcome = "cancelled"
        try:
            with self._uow.transaction():
                task_was_cancelled = not run.is_current()
                input_changed = False
                if not task_was_cancelled:
                    current_context = self.load_resource_context(
                        resource_id=resource_id, source_node_id=source_node_id
                    )
                    task_was_cancelled = current_context is None
                    input_changed = current_context is not None and (
                        current_observation != observation
                        or current_context.node.observed_size_bytes
                        != context.node.observed_size_bytes
                        or current_context.node.observed_mtime_ns
                        != context.node.observed_mtime_ns
                        or current_context.resource.adapter_version
                        != context.resource.adapter_version
                    )
                    if input_changed:
                        run.request_changed(
                            library_id=library_id,
                            resource_id=resource_id,
                            source_node_id=source_node_id,
                        )
                        run.succeed(finished_at=self._clock.now())
                        outcome = "changed"
                if not task_was_cancelled and not input_changed:
                    self.save_asset_result(
                        parsed=parsed,
                        library_id=library_id,
                        resource_id=resource_id,
                        source_node_id=source_node_id,
                        role=role,
                        sort_key=node.relative_path,
                        processed_source_version=processed_version,
                        observations=tuple(
                            LocalMetadataObservation(
                                candidate.source,
                                candidate.metadata,
                                prepared_covers[candidate.source].stored_path
                                if candidate.source in prepared_covers
                                else None,
                            )
                            for candidate in local_metadata.candidates
                        )
                        if local_metadata is not None
                        else None,
                        cover_path=prepared_cover.stored_path
                        if prepared_cover
                        else None,
                    )
                    self.finalize_resource(
                        parsed=parsed,
                        resource_id=resource_id,
                        role=role,
                        local_metadata=local_metadata,
                    )
                    import_succeeded = parsed.ok and parsed.asset is not None
                    outcome = "ok" if import_succeeded else "failed"
                    if not import_succeeded:
                        self._log.emit(
                            "readable_resource.parse_result_failed",
                            error=ImportTaskRuleError(
                                f"Adapter returned ok={parsed.ok}, asset_present={parsed.asset is not None}, "
                                f"error_code={parsed.error_code or 'NOT_PROVIDED'}, reason={parsed.error_summary or 'NOT_PROVIDED'}"
                            ),
                            task_id=task_id,
                            resource_id=resource_id,
                            source_node_id=source_node_id,
                            stage="import",
                            step="read_parse_result",
                            outcome="failed",
                        )
                        run.fail(
                            error_summary=parsed.error_summary
                            or parsed.error_code
                            or "PARSE_FAILED",
                            finished_at=self._clock.now(),
                            result_persisted=True,
                        )
        except Exception:
            if self._covers is not None:
                for prepared in publications:
                    self._covers.discard(prepared)
            raise
        if task_was_cancelled:
            if self._covers is not None:
                for prepared in publications:
                    self._covers.discard(prepared)
            self._log.emit(
                "readable_resource.task.cancelled",
                library_id=library_id,
                resource_id=resource_id,
                task_id=task_id,
                stage="import",
                outcome="cancelled",
            )
            return ProcessTaskResult(task_id=task_id, outcome="cancelled")

        if not import_succeeded and self._covers is not None:
            for prepared in publications:
                self._covers.discard(prepared)
            prepared_covers.clear()
            prepared_cover = None

        if import_succeeded:
            with self._uow.transaction():
                run.succeed(finished_at=self._clock.now())
            self._sidecar.schedule_after_commit(resource_id)
        self._log.emit(
            "readable_resource.task.finished",
            library_id=library_id,
            resource_id=resource_id,
            task_id=task_id,
            stage="import",
            outcome=outcome,
        )
        return ProcessTaskResult(task_id=task_id, outcome=outcome)

    def _refresh_single_file_metadata(
        self,
        task_id: str,
        context: ResourceImportContext,
        absolute: Path,
        *,
        run: ResourceImportRunPort,
    ) -> ProcessTaskResult:
        resource_id = context.resource.id
        observations = self._books_resources.resource_local_observations(resource_id)
        cover_state = self._books_resources.resource_cover_state(resource_id)
        fallback_cover = self._books_resources.single_file_fallback_cover(resource_id)
        self._uow.release_before_io()
        assert context.adapter is not None
        metadata = self._adapters.inspect_resource_metadata(
            resource_absolute_path=absolute,
            adapter=context.adapter,
            local_metadata_priority=context.local_metadata_priority,
        )
        assert metadata is not None
        embedded = tuple(
            LocalMetadataCandidate(
                o.source,
                o.metadata,
                self._covers.read_candidate(o.cover_path)
                if self._covers is not None
                and o.cover_path
                and not cover_state.protected
                else None,
            )
            for o in observations
            if o.source == "EMBEDDED"
        )
        resolved = resolve_local_metadata(
            metadata.candidates + embedded, context.local_metadata_priority
        )
        prepared = None
        cover_path = cover_state.path
        if self._covers is not None and not cover_state.protected:
            for source in context.local_metadata_priority:
                candidate = next(
                    (c for c in resolved.candidates if c.source == source and c.cover),
                    None,
                )
                if candidate is not None:
                    if not self._covers.matches(cover_path, candidate.cover):
                        prepared = self._covers.prepare(
                            resource_id=resource_id, content=candidate.cover
                        )
                    break
            else:
                previous_cover = cover_path
                cover_path = None
                if fallback_cover is not None and self._covers.exists(fallback_cover):
                    cover_path = fallback_cover
                elif (
                    context.resource.format == "PDF"
                    and self._first_page_covers is not None
                ):
                    content = self._first_page_covers.extract(
                        path=absolute, source_format="PDF"
                    )
                    if content is not None:
                        if self._covers.matches(previous_cover, content):
                            cover_path = previous_cover
                        else:
                            prepared = self._covers.prepare(
                                resource_id=resource_id, content=content
                            )
        committed = False
        try:
            if prepared is not None and self._covers is not None:
                self._covers.publish(prepared)
                cover_path = prepared.stored_path
            with self._uow.transaction():
                if (
                    not run.is_current()
                    or self._books_resources.get_resource(resource_id) is None
                ):
                    return ProcessTaskResult(task_id, "cancelled")
                self._books_resources.apply_local_metadata(
                    resource_id=resource_id,
                    metadata=resolved.metadata,
                    cover_path=cover_path,
                )
                run.succeed(finished_at=self._clock.now())
            committed = True
        finally:
            if prepared is not None and not committed and self._covers is not None:
                self._covers.discard(prepared)
        return ProcessTaskResult(task_id, "ok")

    def _execute_directory(
        self,
        task_id: str,
        context: ResourceImportContext,
        *,
        run: ResourceImportRunPort,
    ) -> ProcessTaskResult:
        adapter = context.adapter
        assert adapter is not None
        resource_id = context.resource.id
        library_id = context.resource.library_id
        absolute = self._filesystem.resolve_under_root(
            context.root_path, context.node.relative_path
        )
        changed = False
        batch: list[DirectoryAssetResult] = []
        for item in self._directory_items(resource_id, run):
            if isinstance(item, DirectoryMemberPage):
                if batch and not self._save_directory_batch(
                    task_id, context, tuple(batch), run
                ):
                    return ProcessTaskResult(task_id, "cancelled")
                batch.clear()
                with self._uow.transaction():
                    if not run.is_current():
                        return ProcessTaskResult(task_id, "cancelled")
                    if changed:
                        run.request_changed(
                            library_id=library_id,
                            resource_id=resource_id,
                            source_node_id=context.node.id,
                        )
                    if item.last_visited_id is not None:
                        run.advance_directory_cursor(resource_id, item.last_visited_id)
                changed = False
                if item.full and run.can_yield_directory:
                    return ProcessTaskResult(task_id, "yielded")
                continue
            member = item
            if Path(member.node.name).suffix.lower() not in adapter.file_extensions:
                continue
            path = self._filesystem.resolve_under_root(
                context.root_path, member.node.relative_path
            )
            before = self._filesystem.observe_readable_file(path)
            version = self._processed_version(context, before)
            if (
                member.ready
                and version is not None
                and member.processed_version == version
            ):
                continue
            error = None
            title = mime_type = None
            asset_metadata = None
            units = ()
            observations = ()
            candidate_path = None
            try:
                parsed = self._adapters.parse_file(
                    absolute_path=path,
                    resource_absolute_path=absolute,
                    adapter=adapter,
                    role=adapter.asset_role,
                    local_metadata_priority=context.local_metadata_priority,
                )
                if parsed.ok and parsed.asset is not None:
                    title, mime_type = parsed.asset.title, parsed.asset.mime_type
                    asset = parsed.asset
                    asset_metadata = ResourceAssetMetadataInput(
                        title=title,
                        mime_type=mime_type,
                        duration_ms=asset.duration_ms,
                        codec=asset.technical.codec,
                        bitrate=asset.technical.bitrate,
                        sample_rate=asset.technical.sample_rate,
                        channels=asset.technical.channels,
                        disc_number=asset.technical.disc_number,
                        track_number=asset.technical.track_number,
                    )
                    units = asset.navigation_units
                    retained = []
                    if (
                        adapter.asset_role is AssetRole.TRACK
                        and parsed.local_metadata is not None
                    ):
                        for candidate in parsed.local_metadata.candidates:
                            candidate_path = None
                            if candidate.cover is not None and self._covers is not None:
                                try:
                                    candidate_path = (
                                        self._covers.retain_audio_candidate(
                                            resource_id=resource_id,
                                            content=candidate.cover,
                                        )
                                    )
                                except ValueError as cover_error:
                                    self._log.emit(
                                        "readable_resource.audio_cover.rejected",
                                        error=cover_error,
                                        library_id=library_id,
                                        resource_id=resource_id,
                                        task_id=task_id,
                                        stage="cover_prepare",
                                        outcome="invalid",
                                    )
                                    candidate_path = None
                            retained.append(
                                LocalMetadataObservation(
                                    candidate.source, candidate.metadata, candidate_path
                                )
                            )
                        observations = tuple(retained)
                    # No artwork payload is retained across iterations or batches.
                    del parsed
                else:
                    self._log.emit(
                        "readable_resource.asset_parse_result_failed",
                        error=ImportTaskRuleError(
                            f"Adapter returned ok={parsed.ok}, asset_present={parsed.asset is not None}, "
                            f"error_code={parsed.error_code or 'NOT_PROVIDED'}, reason={parsed.error_summary or 'NOT_PROVIDED'}"
                        ),
                        task_id=task_id,
                        resource_id=resource_id,
                        source_node_id=member.node.id,
                        stage="import",
                        step="read_asset_parse_result",
                        outcome="failed",
                    )
                    error = parsed.error_summary or parsed.error_code or "PARSE_FAILED"
            except OSError as io_error:
                self._log.emit(
                    "readable_resource.asset_unreadable",
                    error=io_error,
                    stage="asset_parse",
                    task_id=task_id,
                    outcome="IMAGE_FILE_UNREADABLE"
                    if adapter.asset_role is AssetRole.PAGE
                    else "AUDIO_FILE_UNREADABLE",
                )
                error = (
                    "IMAGE_FILE_UNREADABLE"
                    if adapter.asset_role is AssetRole.PAGE
                    else "AUDIO_FILE_UNREADABLE"
                )
            after = self._filesystem.observe_readable_file(path)
            if before != after:
                changed = True
                continue
            batch.append(
                DirectoryAssetResult(
                    member.node,
                    version if error is None else None,
                    title,
                    mime_type,
                    error,
                    metadata=asset_metadata,
                    units=units,
                    observations=observations,
                )
            )
            if len(batch) == 200:
                if not self._save_directory_batch(task_id, context, tuple(batch), run):
                    return ProcessTaskResult(task_id, "cancelled")
                batch.clear()
        errors = self._books_resources.has_failed_directory_assets(resource_id)

        # Directory candidates are inspected once; file observations remain file-owned.
        with self._uow.transaction():
            if not run.is_current():
                return ProcessTaskResult(task_id, "cancelled")
            cover_state = self._books_resources.resource_cover_state(resource_id)
        self._uow.release_before_io()
        metadata = self._adapters.inspect_resource_metadata(
            resource_absolute_path=absolute,
            adapter=adapter,
            local_metadata_priority=context.local_metadata_priority,
        )
        if metadata is None:
            raise ValueError("DIRECTORY_METADATA_UNAVAILABLE")
        if adapter.asset_role is AssetRole.TRACK:
            observations = self._books_resources.resource_local_observations(
                resource_id
            )
            self._uow.release_before_io()
            grouped = merge_observations(observations)
            embedded_candidates = []
            for source, values in grouped.items():
                cover = None
                if self._covers is not None and not cover_state.protected:
                    for observation in observations:
                        if (
                            observation.source == source
                            and observation.cover_path is not None
                        ):
                            cover = self._covers.read_candidate(observation.cover_path)
                            if cover is not None:
                                break
                embedded_candidates.append(
                    LocalMetadataCandidate(source, values, cover)
                )
            metadata = resolve_local_metadata(
                metadata.candidates + tuple(embedded_candidates),
                context.local_metadata_priority,
            )
        prepared = None
        cover_path = cover_state.path
        if not cover_state.protected and self._covers is not None:
            contents = (
                c.cover
                for source in context.local_metadata_priority
                for c in metadata.candidates
                if c.source == source and c.cover is not None
            )
            for content in contents:
                if self._covers.matches(cover_path, content):
                    break
                try:
                    prepared = self._covers.prepare(
                        resource_id=resource_id, content=content
                    )
                    break
                except ValueError as cover_error:
                    self._log.emit(
                        "readable_resource.directory_cover.rejected",
                        error=cover_error,
                        library_id=library_id,
                        resource_id=resource_id,
                        task_id=task_id,
                        stage="cover_prepare",
                        outcome="invalid",
                    )
                    continue
            else:
                previous_cover = cover_path
                cover_path = None
                if (
                    self._first_page_covers is not None
                    and adapter.asset_role is AssetRole.PAGE
                ):
                    cover_cursor = run.directory_cover_cursor(resource_id)
                    while True:
                        candidates = self._books_resources.page_ready_directory_cover_candidates(
                            resource_id, after_asset_id=cover_cursor, limit=16
                        )
                        self._uow.release_before_io()
                        selected = False
                        for cover_candidate in candidates:
                            if (
                                Path(cover_candidate.node.name).suffix.lower()
                                not in adapter.file_extensions
                            ):
                                continue
                            cover_content = self._first_page_covers.extract(
                                path=self._filesystem.resolve_under_root(
                                    context.root_path, cover_candidate.node.relative_path
                                ),
                                source_format="IMAGE_DIR",
                            )
                            if cover_content is None:
                                continue
                            if self._covers.matches(previous_cover, cover_content):
                                cover_path = previous_cover
                                selected = True
                                break
                            try:
                                prepared = self._covers.prepare(
                                    resource_id=resource_id, content=cover_content
                                )
                                selected = True
                                break
                            except ValueError as cover_error:
                                self._log.emit(
                                    "readable_resource.first_page_cover.rejected",
                                    error=cover_error,
                                    library_id=library_id,
                                    resource_id=resource_id,
                                    task_id=task_id,
                                    stage="cover_prepare",
                                    outcome="invalid",
                                )
                        if selected or len(candidates) < 16:
                            break
                        cover_cursor = candidates[-1].asset_id
                        if run.can_yield_directory:
                            with self._uow.transaction():
                                if not run.is_current():
                                    return ProcessTaskResult(task_id, "cancelled")
                                run.advance_directory_cover_cursor(resource_id, cover_cursor)
                            return ProcessTaskResult(task_id, "yielded")
        committed = False
        try:
            if prepared is not None and self._covers is not None:
                self._covers.publish(prepared)
                cover_path = prepared.stored_path
            with self._uow.transaction():
                if not run.is_current():
                    return ProcessTaskResult(task_id, "cancelled")
                count = self._books_resources.count_ready_assets(resource_id)
                if count:
                    self._books_resources.mark_resource_ready(resource_id=resource_id)
                else:
                    self._books_resources.mark_resource_failed(resource_id)
                self._books_resources.apply_local_metadata(
                    resource_id=resource_id,
                    metadata=metadata.metadata,
                    cover_path=cover_path,
                )
                if adapter.asset_role is AssetRole.TRACK:
                    self._books_resources.refresh_audio_resource_aggregates(resource_id)
                else:
                    self._books_resources.set_resource_page_count(resource_id, count)
                if errors:
                    run.fail(
                        error_summary="IMAGE_ASSETS_FAILED"
                        if adapter.asset_role is AssetRole.PAGE
                        else "AUDIO_ASSETS_FAILED",
                        finished_at=self._clock.now(),
                        result_persisted=True,
                    )
                else:
                    run.succeed(finished_at=self._clock.now())
            committed = True
        finally:
            if prepared is not None and not committed and self._covers is not None:
                self._covers.discard(prepared)
        return ProcessTaskResult(
            task_id, "failed" if errors else "changed" if changed else "ok"
        )

    def _save_directory_batch(
        self,
        task_id: str,
        context: ResourceImportContext,
        results: tuple[DirectoryAssetResult, ...],
        run: ResourceImportRunPort,
    ) -> bool:
        with self._uow.transaction():
            if not run.is_current():
                return False
            self._books_resources.save_directory_assets(
                library_id=context.resource.library_id,
                resource_id=context.resource.id,
                results=results,
            )
        self._uow.release_before_io()
        return True

    def _directory_items(
        self, resource_id: str, run: ResourceImportRunPort
    ) -> Iterator[DirectoryImportMember | DirectoryMemberPage]:
        cursor = run.directory_cursor(resource_id)
        while True:
            page = self._books_resources.page_directory_members(
                resource_id, after_id=cursor, limit=128
            )
            self._uow.release_before_io()
            yield from page.members
            yield page
            if not page.full:
                return
            cursor = page.last_visited_id


    @staticmethod
    def _processed_version(
        context: ResourceImportContext,
        observation: RegularFileObservation | None,
    ) -> str | None:
        if observation is None:
            return None
        return json.dumps(
            [
                observation.observed_size_bytes,
                observation.observed_mtime_ns,
                context.resource.adapter_id,
                context.adapter.adapter_version
                if context.adapter is not None
                else context.resource.adapter_version,
                context.resource.format,
            ],
            separators=(",", ":"),
        )

    def load_resource_context(
        self, *, resource_id: str, source_node_id: str
    ) -> ResourceImportContext | None:
        """Read immutable import inputs; callers close the read scope before I/O."""
        resource = self._books_resources.get_resource(resource_id)
        node = self._source_nodes.get(source_node_id)
        resource_node = (
            self._source_nodes.get(resource.source_node_id) if resource else None
        )
        if resource is None or node is None or resource_node is None:
            return None
        return ResourceImportContext(
            resource=resource,
            node=node,
            resource_node=resource_node,
            root_path=self._libraries.get_library(resource.library_id).root_path,
            adapter=self._resolve_adapter(resource.adapter_id),
            local_metadata_priority=(
                self._metadata_priority.load()
                if self._metadata_priority is not None
                else DEFAULT_LOCAL_METADATA_PRIORITY
            ),
        )

    def prepare_resource_covers(
        self,
        *,
        context: ResourceImportContext,
        parsed: FileParseResult,
        local_metadata: ResolvedLocalMetadata | None,
        absolute: Path,
        task_id: str,
    ) -> PreparedResourceCovers:
        """Prepare resource artwork outside the persistence transaction."""
        resource = context.resource
        resource_id = resource.id
        library_id = resource.library_id
        source_node_id = context.node.id
        local_metadata_priority = context.local_metadata_priority
        prepared_covers: dict[LocalMetadataSource, PreparedLocalCover] = {}
        if local_metadata is not None and self._covers is not None:
            try:
                for candidate in local_metadata.candidates:
                    if candidate.cover is None:
                        continue
                    try:
                        prepared_covers[candidate.source] = self._covers.prepare(
                            resource_id=f"{resource.id}-{source_node_id}-{candidate.source}",
                            content=candidate.cover,
                        )
                    except ValueError as error:
                        self._log.emit(
                            "readable_resource.local_cover.rejected",
                            error=error,
                            library_id=library_id,
                            resource_id=resource_id,
                            task_id=task_id,
                            stage="local_metadata",
                            outcome="invalid",
                        )
            except Exception:
                for prepared in prepared_covers.values():
                    self._covers.discard(prepared)
                raise
        prepared_cover = next(
            (
                prepared_covers[source]
                for source in local_metadata_priority
                if source in prepared_covers
            ),
            None,
        )

        publications = list(prepared_covers.values())
        if (
            parsed.ok
            and parsed.asset is not None
            and prepared_cover is None
            and self._covers is not None
            and self._first_page_covers is not None
            and resource.format == "PDF"
        ):
            should_extract = self._books_resources.should_extract_first_page_cover(
                resource_id=resource_id, source_node_id=source_node_id
            )
            self._uow.release_before_io()
            if should_extract:
                content = self._first_page_covers.extract(
                    path=absolute, source_format=resource.format
                )
                if content is not None:
                    try:
                        prepared_cover = self._covers.prepare(
                            resource_id=f"{resource_id}-{source_node_id}-first-page",
                            content=content,
                        )
                    except ValueError as error:
                        self._log.emit(
                            "readable_resource.first_page_cover.rejected",
                            error=error,
                            library_id=library_id,
                            resource_id=resource_id,
                            task_id=task_id,
                            stage="cover_prepare",
                            outcome="invalid",
                        )
                        prepared_cover = None
                    if prepared_cover is not None:
                        publications.append(prepared_cover)

        return PreparedResourceCovers(
            selected=prepared_cover,
            candidates=prepared_covers,
            publications=tuple(publications),
        )

    def save_asset_result(
        self,
        *,
        parsed: FileParseResult,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
        sort_key: str,
        observations: tuple[LocalMetadataObservation, ...] | None = None,
        cover_path: str | None = None,
        processed_source_version: str | None = None,
    ) -> str:
        """Save only this file and its navigation in the caller's transaction.

        No queue transitions, resource metadata, ordering, counts or cover I/O.
        Cover paths must already be published. Observations may include the
        separately inspected directory context used by the legacy entry.
        The existing repository remains the authority for topology validation.
        """
        if parsed.ok and parsed.asset is not None:
            asset_id = self._books_resources.upsert_asset(
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                role=parsed.asset.role,
                import_state=AssetImportState.READY,
                sequence_index=parsed.asset.sequence_index,
                sort_key=sort_key,
                failure_reason=None,
                processed_source_version=processed_source_version,
                metadata=ResourceAssetMetadataInput(
                    title=parsed.asset.title,
                    mime_type=parsed.asset.mime_type,
                    duration_ms=parsed.asset.duration_ms,
                    codec=parsed.asset.technical.codec,
                    bitrate=parsed.asset.technical.bitrate,
                    sample_rate=parsed.asset.technical.sample_rate,
                    channels=parsed.asset.technical.channels,
                    disc_number=parsed.asset.technical.disc_number,
                    track_number=parsed.asset.technical.track_number,
                ),
            )
            self._books_resources.replace_navigation_units(
                resource_id=resource_id,
                asset_id=asset_id,
                units=parsed.asset.navigation_units,
            )
            if parsed.local_metadata is not None or observations is not None:
                self._books_resources.save_asset_local_metadata(
                    resource_id=resource_id,
                    asset_id=asset_id,
                    observations=(
                        observations
                        if observations is not None
                        else tuple(
                            LocalMetadataObservation(
                                candidate.source, candidate.metadata, None
                            )
                            for candidate in parsed.local_metadata.candidates
                        )
                        if parsed.local_metadata is not None
                        else ()
                    ),
                    cover_path=cover_path,
                )
            return asset_id

        summary = parsed.error_summary or parsed.error_code or "PARSE_FAILED"
        return self._books_resources.upsert_asset(
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=role,
            import_state=AssetImportState.FAILED,
            sequence_index=None,
            sort_key=None,
            failure_reason=summary,
        )

    def finalize_resource(
        self,
        *,
        parsed: FileParseResult,
        local_metadata: ResolvedLocalMetadata | None,
        resource_id: str,
        role: AssetRole,
    ) -> None:
        """Apply resource effects after cover publication, in the caller's transaction.

        The single-file entry calls this once. Directory entries finalize after
        their asset batches; this method does not commit or finish tasks.
        """
        ready_assets = self._books_resources.count_ready_assets(resource_id)
        if parsed.ok and parsed.asset is not None:
            if ready_assets >= 1:
                self._books_resources.mark_resource_ready(
                    resource_id=resource_id,
                    title=(
                        local_metadata.metadata.volume_title
                        or local_metadata.metadata.title
                        if local_metadata is not None
                        else parsed.resource_title
                    ),
                )
                page_units = tuple(
                    unit
                    for unit in parsed.asset.navigation_units
                    if unit.unit_type == "page"
                )
                if page_units and len(page_units) == len(parsed.asset.navigation_units):
                    self._books_resources.set_resource_page_count(
                        resource_id, len(page_units)
                    )
                elif parsed.asset.role is AssetRole.PRIMARY and not page_units:
                    self._books_resources.set_resource_page_count(
                        resource_id, parsed.asset.technical.page_count
                    )
                if parsed.asset.role is AssetRole.TRACK:
                    self._books_resources.refresh_audio_resource_aggregates(resource_id)
            if local_metadata is not None:
                self._books_resources.refresh_resource_local_metadata(resource_id)
        else:
            if role is AssetRole.TRACK and ready_assets >= 1:
                self._books_resources.refresh_audio_resource_aggregates(resource_id)
            if ready_assets < 1:
                self._books_resources.mark_resource_failed(resource_id)

    def _resolve_adapter(self, adapter_id: str) -> ResourceAdapterSpec | None:
        return next(
            (spec for spec in ADAPTER_SPECS if spec.adapter_id.value == adapter_id),
            None,
        )


__all__ = [
    "ProcessReadableResourceImportTask",
    "ProcessTaskResult",
    "ResourceImportRunPort",
]
