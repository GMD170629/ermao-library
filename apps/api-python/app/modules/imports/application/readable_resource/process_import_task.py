"""Process resource tasks and legacy directory assets through shared file operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.local_metadata_snapshot import LocalMetadataObservation
from app.core.natural_sort import natural_sort_key
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
    ImageAssetResult,
    ResourceAssetMetadataInput,
    SourceNodePhysicalKind,
)
from app.modules.media.public import FirstPageCoverPort
from app.modules.metadata.public import ResolvedLocalMetadata, resolve_local_metadata


@dataclass(frozen=True, slots=True)
class ProcessTaskResult:
    task_id: str
    outcome: str


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
            if task is None or task.kind not in {"IMPORT_ASSET", "IMPORT_RESOURCE"}:
                return ProcessTaskResult(task_id=task_id, outcome="missing_task")
            if (
                task.resource_id is None
                or task.source_node_id is None
                or (task.kind == "IMPORT_ASSET" and task.role is None)
            ):
                self._queue.mark_failed(
                    task_id,
                    error_summary="INVALID_TASK_SHAPE",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="invalid_task")
            context = self.load_resource_context(
                resource_id=task.resource_id, source_node_id=task.source_node_id
            )
            if context is None:
                self._queue.mark_failed(
                    task_id,
                    error_summary="MISSING_TARGETS",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="missing_targets")
            adapter = context.adapter
            if adapter is None:
                self._queue.mark_failed(
                    task_id,
                    error_summary="UNKNOWN_ADAPTER",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")
            resource_is_image = context.resource.format == "IMAGE_DIR"
            if resource_is_image and task.kind != "IMPORT_RESOURCE":
                self._queue.mark_failed(
                    task_id,
                    error_summary="RESOURCE_TASK_REQUIRED",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id, "invalid_task")
            if task.kind == "IMPORT_RESOURCE":
                if (
                    (adapter.is_directory_adapter and not resource_is_image)
                    or context.node.id != context.resource.source_node_id
                    or context.node.physical_kind
                    is not (
                        SourceNodePhysicalKind.DIRECTORY
                        if resource_is_image
                        else SourceNodePhysicalKind.REGULAR_FILE
                    )
                    or context.resource.library_id != task.library_id
                ):
                    self._queue.mark_failed(
                        task_id,
                        error_summary="INVALID_RESOURCE_TASK_TARGET",
                        finished_at=self._clock.now(),
                    )
                    return ProcessTaskResult(task_id=task_id, outcome="invalid_task")
                if task.state != "RUNNING":
                    self._queue.mark_running(task_id, started_at=self._clock.now())
            resource = context.resource
            node = context.node
            relative_path = node.relative_path
            resource_relative_path = context.resource_node.relative_path
            root_path = context.root_path
            role = adapter.asset_role if task.kind == "IMPORT_RESOURCE" else task.role
            assert role is not None
            resource_id = resource.id
            library_id = resource.library_id
            source_node_id = task.source_node_id
            local_metadata_priority = context.local_metadata_priority

        if resource_is_image:
            return self._execute_images(task_id, context)
        self._uow.release_before_io()
        absolute = self._filesystem.resolve_under_root(root_path, relative_path)
        resource_absolute = self._filesystem.resolve_under_root(
            root_path, resource_relative_path
        )
        observation = (
            self._filesystem.observe_readable_file(absolute)
            if task.kind == "IMPORT_RESOURCE"
            else None
        )
        processed_version = self._processed_version(context, observation)
        if processed_version is not None:
            already_processed = self._books_resources.asset_has_processed_version(
                resource_id=resource_id,
                source_node_id=source_node_id,
                version=processed_version,
            )
            self._uow.release_before_io()
            if already_processed:
                with self._uow.transaction():
                    if self._queue.get_task(task_id) is None:
                        return ProcessTaskResult(task_id=task_id, outcome="cancelled")
                    self._queue.mark_succeeded(task_id, finished_at=self._clock.now())
                return ProcessTaskResult(task_id=task_id, outcome="ok")
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
            except OSError:
                for prepared in publications:
                    self._covers.discard(prepared)
                with self._uow.transaction():
                    if self._queue.get_task(task_id) is None:
                        return ProcessTaskResult(task_id=task_id, outcome="cancelled")
                    self._queue.mark_failed(
                        task_id,
                        error_summary="COVER_PUBLISH_FAILED",
                        finished_at=self._clock.now(),
                    )
                return ProcessTaskResult(task_id=task_id, outcome="failed")

        current_observation = (
            self._filesystem.observe_readable_file(absolute)
            if task.kind == "IMPORT_RESOURCE"
            else None
        )
        import_succeeded = False
        outcome = "cancelled"
        try:
            with self._uow.transaction():
                current_task = self._queue.get_task(task_id)
                task_was_cancelled = current_task is None
                input_changed = False
                if not task_was_cancelled and task.kind == "IMPORT_RESOURCE":
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
                        self._queue.request_import_resource(
                            library_id=library_id,
                            resource_id=resource_id,
                            source_node_id=source_node_id,
                            changed=True,
                        )
                        self._queue.mark_succeeded(
                            task_id, finished_at=self._clock.now()
                        )
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
                        self._queue.mark_failed(
                            task_id,
                            error_summary=parsed.error_summary
                            or parsed.error_code
                            or "PARSE_FAILED",
                            finished_at=self._clock.now(),
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
                self._queue.mark_succeeded(task_id, finished_at=self._clock.now())
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

    def _execute_images(
        self, task_id: str, context: ResourceImportContext
    ) -> ProcessTaskResult:
        adapter = context.adapter
        assert adapter is not None
        resource_id = context.resource.id
        library_id = context.resource.library_id
        members = sorted(
            (
                m
                for m in self._books_resources.load_image_members(resource_id)
                if Path(m.node.name).suffix.lower() in adapter.file_extensions
            ),
            key=lambda m: natural_sort_key(m.node.relative_path),
        )
        self._uow.release_before_io()
        absolute = self._filesystem.resolve_under_root(
            context.root_path, context.node.relative_path
        )
        ready = {m.node.id for m in members if m.ready}
        errors = False
        changed = False
        batch: list[ImageAssetResult] = []
        for member in members:
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
            try:
                parsed = self._adapters.parse_file(
                    absolute_path=path,
                    resource_absolute_path=absolute,
                    adapter=adapter,
                    role=AssetRole.PAGE,
                    local_metadata_priority=context.local_metadata_priority,
                )
                if parsed.ok and parsed.asset is not None:
                    title, mime_type = parsed.asset.title, parsed.asset.mime_type
                else:
                    error = parsed.error_summary or parsed.error_code or "PARSE_FAILED"
            except OSError:
                error = "IMAGE_FILE_UNREADABLE"
            after = self._filesystem.observe_readable_file(path)
            if before != after:
                changed = True
                continue
            errors |= error is not None
            if error is None:
                ready.add(member.node.id)
            else:
                ready.discard(member.node.id)
            batch.append(
                ImageAssetResult(
                    member.node,
                    version if error is None else None,
                    title,
                    mime_type,
                    error,
                )
            )
            if len(batch) == 200:
                if not self._save_image_batch(task_id, context, tuple(batch)):
                    return ProcessTaskResult(task_id, "cancelled")
                batch.clear()
        if batch and not self._save_image_batch(task_id, context, tuple(batch)):
            return ProcessTaskResult(task_id, "cancelled")

        # Only directory-owned candidates are resolved; pages own no directory snapshot.
        with self._uow.transaction():
            if self._queue.get_task(task_id) is None:
                return ProcessTaskResult(task_id, "cancelled")
            cover_state = self._books_resources.resource_cover_state(resource_id)
        self._uow.release_before_io()
        metadata = self._adapters.inspect_resource_metadata(
            resource_absolute_path=absolute,
            adapter=adapter,
            local_metadata_priority=context.local_metadata_priority,
        )
        if metadata is None:
            raise ValueError("IMAGE_DIRECTORY_METADATA_UNAVAILABLE")
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
                except ValueError:
                    continue
            else:
                if self._first_page_covers is not None:
                    for member in members:
                        if member.node.id not in ready:
                            continue
                        content = self._first_page_covers.extract(
                            path=self._filesystem.resolve_under_root(
                                context.root_path, member.node.relative_path
                            ),
                            source_format="IMAGE_DIR",
                        )
                        if content is None:
                            continue
                        if self._covers.matches(cover_path, content):
                            break
                        try:
                            prepared = self._covers.prepare(
                                resource_id=resource_id, content=content
                            )
                            break
                        except ValueError:
                            continue
        committed = False
        try:
            if prepared is not None and self._covers is not None:
                self._covers.publish(prepared)
                cover_path = prepared.stored_path
            with self._uow.transaction():
                if self._queue.get_task(task_id) is None:
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
                self._books_resources.set_resource_page_count(resource_id, count)
                if changed:
                    self._queue.request_import_resource(
                        library_id=library_id,
                        resource_id=resource_id,
                        source_node_id=context.node.id,
                        changed=True,
                    )
                if errors:
                    self._queue.mark_failed(
                        task_id,
                        error_summary="IMAGE_ASSETS_FAILED",
                        finished_at=self._clock.now(),
                    )
                else:
                    self._queue.mark_succeeded(task_id, finished_at=self._clock.now())
            committed = True
        finally:
            if prepared is not None and not committed and self._covers is not None:
                self._covers.discard(prepared)
        return ProcessTaskResult(
            task_id, "failed" if errors else "changed" if changed else "ok"
        )

    def _save_image_batch(
        self,
        task_id: str,
        context: ResourceImportContext,
        results: tuple[ImageAssetResult, ...],
    ) -> bool:
        with self._uow.transaction():
            if self._queue.get_task(task_id) is None:
                return False
            self._books_resources.save_image_assets(
                library_id=context.resource.library_id,
                resource_id=context.resource.id,
                results=results,
            )
        self._uow.release_before_io()
        return True

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
                    except ValueError:
                        self._log.emit(
                            "readable_resource.local_cover.rejected",
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
                    except ValueError:
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

        IMPORT_ASSET still calls this once per file. Scheduling and queue completion
        remain owned by execute; this method does not commit or finish tasks.
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


__all__ = ["ProcessReadableResourceImportTask", "ProcessTaskResult"]
