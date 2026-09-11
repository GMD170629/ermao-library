"""Process one IMPORT_ASSET task: parse outside txn, upsert stable Asset."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
)
from app.contracts.local_metadata_snapshot import LocalMetadataObservation
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
    ResourceAdapterExecutorPort,
    SidecarWritebackPort,
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
    ResourceAssetMetadataInput,
)


@dataclass(frozen=True, slots=True)
class ProcessTaskResult:
    task_id: str
    outcome: str


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

    def reset_inspection_cache(self) -> None:
        self._adapters.reset_inspection_cache()

    def execute(self, task_id: str) -> ProcessTaskResult:
        with self._uow.transaction():
            task = self._queue.get_task(task_id)
            if task is None or task.kind != "IMPORT_ASSET":
                return ProcessTaskResult(task_id=task_id, outcome="missing_task")
            if (
                task.resource_id is None
                or task.source_node_id is None
                or task.role is None
            ):
                self._queue.mark_failed(
                    task_id,
                    error_summary="INVALID_TASK_SHAPE",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="invalid_task")
            resource = self._books_resources.get_resource(task.resource_id)
            node = self._source_nodes.get(task.source_node_id)
            resource_node = (
                self._source_nodes.get(resource.source_node_id)
                if resource is not None
                else None
            )
            if resource is None or node is None or resource_node is None:
                self._queue.mark_failed(
                    task_id,
                    error_summary="MISSING_TARGETS",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="missing_targets")
            adapter = self._resolve_adapter(resource.adapter_id)
            if adapter is None:
                self._queue.mark_failed(
                    task_id,
                    error_summary="UNKNOWN_ADAPTER",
                    finished_at=self._clock.now(),
                )
                return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")
            config = self._libraries.get_library(resource.library_id)
            relative_path = node.relative_path
            resource_relative_path = resource_node.relative_path
            root_path = config.root_path
            role = task.role
            resource_id = resource.id
            library_id = resource.library_id
            source_node_id = task.source_node_id
            local_metadata_priority = (
                self._metadata_priority.load()
                if self._metadata_priority is not None
                else DEFAULT_LOCAL_METADATA_PRIORITY
            )

        self._uow.release_before_io()
        absolute = self._filesystem.resolve_under_root(root_path, relative_path)
        resource_absolute = self._filesystem.resolve_under_root(
            root_path, resource_relative_path
        )
        parsed = self._adapters.parse_file(
            absolute_path=absolute,
            resource_absolute_path=resource_absolute,
            adapter=adapter,
            role=role,
            local_metadata_priority=local_metadata_priority,
        )
        prepared_covers: dict[LocalMetadataSource, PreparedLocalCover] = {}
        if parsed.local_metadata is not None and self._covers is not None:
            try:
                for candidate in parsed.local_metadata.candidates:
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

        # Publish new immutable versions before exposing their database references.
        # Failure or cancellation can discard them without touching existing covers.
        if self._covers is not None:
            try:
                for prepared in prepared_covers.values():
                    self._covers.publish(prepared)
            except OSError:
                for prepared in prepared_covers.values():
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

        import_succeeded = False
        outcome = "cancelled"
        try:
            with self._uow.transaction():
                current_task = self._queue.get_task(task_id)
                task_was_cancelled = current_task is None
                if not task_was_cancelled:
                    import_succeeded, outcome = self._persist_parse_result(
                        task_id=task_id,
                        parsed=parsed,
                        prepared_cover=prepared_cover,
                        cover_candidates=prepared_covers,
                        library_id=library_id,
                        resource_id=resource_id,
                        source_node_id=source_node_id,
                        role=role,
                        sort_key=node.relative_path,
                    )
        except Exception:
            if self._covers is not None:
                for prepared in prepared_covers.values():
                    self._covers.discard(prepared)
            raise
        if task_was_cancelled:
            if self._covers is not None:
                for prepared in prepared_covers.values():
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
            for prepared in prepared_covers.values():
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

    def _persist_parse_result(
        self,
        *,
        task_id: str,
        parsed: FileParseResult,
        prepared_cover: PreparedLocalCover | None,
        cover_candidates: dict[LocalMetadataSource, PreparedLocalCover],
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
        sort_key: str,
    ) -> tuple[bool, str]:
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
            title = parsed.resource_title
            resource_ready = self._books_resources.count_ready_assets(resource_id) >= 1
            if resource_ready:
                # Create resource metadata before navigation updates its page count.
                self._books_resources.mark_resource_ready(
                    resource_id=resource_id,
                    title=title,
                )
            self._books_resources.replace_navigation_units(
                resource_id=resource_id,
                asset_id=asset_id,
                units=parsed.asset.navigation_units,
            )
            if resource_ready:
                if parsed.asset.role is AssetRole.PRIMARY and not any(
                    unit.unit_type == "page" for unit in parsed.asset.navigation_units
                ):
                    self._books_resources.set_resource_page_count(
                        resource_id,
                        parsed.asset.technical.page_count,
                    )
                if parsed.asset.role is AssetRole.TRACK:
                    self._books_resources.refresh_audio_resource_aggregates(resource_id)
            if parsed.local_metadata is not None:
                self._books_resources.apply_local_metadata(
                    resource_id=resource_id,
                    metadata=parsed.local_metadata.metadata,
                    asset_id=asset_id,
                    observations=tuple(
                        LocalMetadataObservation(
                            c.source,
                            c.metadata,
                            cover_candidates[c.source].stored_path
                            if c.source in cover_candidates
                            else None,
                        )
                        for c in parsed.local_metadata.candidates
                    ),
                    cover_path=(
                        prepared_cover.stored_path
                        if prepared_cover is not None
                        else None
                    ),
                )
            return (True, "ok")

        summary = parsed.error_summary or parsed.error_code or "PARSE_FAILED"
        self._books_resources.upsert_asset(
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=role,
            import_state=AssetImportState.FAILED,
            sequence_index=None,
            sort_key=None,
            failure_reason=summary,
        )
        ready_assets = self._books_resources.count_ready_assets(resource_id)
        if role is AssetRole.TRACK and ready_assets >= 1:
            self._books_resources.refresh_audio_resource_aggregates(resource_id)
        if ready_assets < 1:
            self._books_resources.mark_resource_failed(resource_id)
        self._queue.mark_failed(
            task_id,
            error_summary=summary,
            finished_at=self._clock.now(),
        )
        return (False, "failed")

    def _resolve_adapter(self, adapter_id: str) -> ResourceAdapterSpec | None:
        return next(
            (spec for spec in ADAPTER_SPECS if spec.adapter_id.value == adapter_id),
            None,
        )


__all__ = ["ProcessReadableResourceImportTask", "ProcessTaskResult"]
