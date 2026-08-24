"""Process one IMPORT_ASSET task: parse outside txn, upsert stable Asset."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.local_metadata import DEFAULT_LOCAL_METADATA_PRIORITY
from app.modules.imports.application.readable_resource.ports import (
    BookResourceRepositoryPort,
    ClockPort,
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LocalCoverPublicationPort,
    LocalMetadataPriorityPort,
    PipelineLogPort,
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
from app.modules.library.domain.readable_resource_states import AssetImportState


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
            if resource is None or node is None:
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
        parsed = self._adapters.parse_file(
            absolute_path=absolute,
            adapter=adapter,
            role=role,
            local_metadata_priority=local_metadata_priority,
        )
        prepared_cover = None
        if (
            parsed.local_metadata is not None
            and parsed.local_metadata.cover is not None
            and self._covers is not None
        ):
            try:
                prepared_cover = self._covers.prepare(
                    resource_id=resource.id,
                    content=parsed.local_metadata.cover.content,
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
                prepared_cover = None

        import_succeeded = False
        with self._uow.transaction():
            if parsed.ok and parsed.asset is not None:
                asset_id = self._books_resources.upsert_asset(
                    library_id=library_id,
                    resource_id=resource_id,
                    source_node_id=source_node_id,
                    role=parsed.asset.role,
                    import_state=AssetImportState.READY,
                    sequence_index=parsed.asset.sequence_index,
                    sort_key=parsed.asset.sort_key,
                    failure_reason=None,
                )
                title = parsed.resource_title or parsed.asset.title
                if parsed.local_metadata is not None:
                    self._books_resources.apply_local_metadata(
                        resource_id=resource_id,
                        metadata=parsed.local_metadata.metadata,
                        cover_path=(
                            prepared_cover.stored_path
                            if prepared_cover is not None
                            else None
                        ),
                    )
                if parsed.asset.navigation_units:
                    self._books_resources.replace_navigation_units(
                        resource_id=resource_id,
                        asset_id=asset_id,
                        units=parsed.asset.navigation_units,
                    )
                if self._books_resources.count_ready_assets(resource_id) >= 1:
                    self._books_resources.mark_resource_ready(
                        resource_id=resource_id,
                        title=title,
                    )
                    if parsed.asset.technical.page_count is not None:
                        self._books_resources.set_resource_page_count(
                            resource_id,
                            parsed.asset.technical.page_count,
                        )
                import_succeeded = True
                outcome = "ok"
            else:
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
                if self._books_resources.count_ready_assets(resource_id) < 1:
                    self._books_resources.mark_resource_failed(resource_id)
                self._queue.mark_failed(
                    task_id,
                    error_summary=summary,
                    finished_at=self._clock.now(),
                )
                outcome = "failed"

        if (
            not import_succeeded
            and prepared_cover is not None
            and self._covers is not None
        ):
            self._covers.discard(prepared_cover)
            prepared_cover = None

        if prepared_cover is not None and self._covers is not None:
            try:
                self._covers.publish(prepared_cover)
            except OSError:
                self._covers.discard(prepared_cover)
                with self._uow.transaction():
                    self._books_resources.clear_local_cover(
                        resource_id=resource_id,
                        expected_path=prepared_cover.stored_path,
                    )
                    self._queue.mark_failed(
                        task_id,
                        error_summary="COVER_PUBLISH_FAILED",
                        finished_at=self._clock.now(),
                    )
                import_succeeded = False
                outcome = "failed"
                self._log.emit(
                    "readable_resource.local_cover.publish_failed",
                    library_id=library_id,
                    resource_id=resource_id,
                    task_id=task_id,
                    stage="local_metadata",
                    outcome="infrastructure_failure",
                )

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

    def _resolve_adapter(self, adapter_id: str) -> ResourceAdapterSpec | None:
        return next(
            (spec for spec in ADAPTER_SPECS if spec.adapter_id.value == adapter_id),
            None,
        )


__all__ = ["ProcessReadableResourceImportTask", "ProcessTaskResult"]
