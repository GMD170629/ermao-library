"""Process one LibraryImportTask outside then inside a short transaction."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    BookResourceRepositoryPort,
    ClockPort,
    FileParseResult,
    ImportRunRepositoryPort,
    LibraryConfigPort,
    PipelineLogPort,
    ResourceAdapterExecutorPort,
    SidecarWritebackPort,
    SourceNodeRepositoryPort,
    SourceTreeFilesystemPort,
    UnitOfWorkPort,
    WorkQueuePort,
)
from app.modules.imports.domain.import_run_policies import (
    LibraryImportTaskState,
    finalize_run_state,
    may_commit_incremental_result,
    may_commit_run_owned_result,
)
from app.modules.imports.domain.resource_adapters import ADAPTER_SPECS
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    ResourceImportState,
    meets_minimum_ready_assets,
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
        import_runs: ImportRunRepositoryPort,
        adapters: ResourceAdapterExecutorPort,
        queue: WorkQueuePort,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        log: PipelineLogPort,
        sidecar: SidecarWritebackPort,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._import_runs = import_runs
        self._adapters = adapters
        self._queue = queue
        self._uow = uow
        self._clock = clock
        self._log = log
        self._sidecar = sidecar

    def execute(self, task_id: str) -> ProcessTaskResult:
        task = self._import_runs.get_task(task_id)
        if task is None:
            return ProcessTaskResult(task_id=task_id, outcome="missing_task")
        resource = self._books_resources.get_resource(task.resource_id)
        node = self._source_nodes.get(task.source_node_id)
        if resource is None or node is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary="resource_or_source_missing",
                increment_attempt=True,
            )
            self._uow.commit()
            return ProcessTaskResult(task_id=task_id, outcome="missing_targets")

        adapter = next(
            (spec for spec in ADAPTER_SPECS if spec.adapter_id.value == resource.adapter_id),
            None,
        )
        if adapter is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary="unknown_adapter",
                increment_attempt=True,
            )
            self._uow.commit()
            return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")

        config = self._libraries.get_library(resource.library_id)
        absolute = self._filesystem.resolve_under_root(
            config.root_path, node.relative_path
        )
        # Transaction-free file parse.
        parsed = self._adapters.parse_file(
            absolute_path=absolute,
            adapter=adapter,
            role=task.role,
        )

        self._import_runs.mark_task_state(
            task_id,
            LibraryImportTaskState.RUNNING,
            increment_attempt=True,
        )
        if task.owner_import_run_id is not None:
            allowed = may_commit_run_owned_result(
                resource_active_import_run_id=resource.active_import_run_id,
                task_owner_import_run_id=task.owner_import_run_id,
            )
        else:
            allowed = may_commit_incremental_result(
                resource_active_import_run_id=resource.active_import_run_id,
                task_owner_import_run_id=task.owner_import_run_id,
            )
        if not allowed:
            self._import_runs.mark_task_state(task_id, LibraryImportTaskState.QUEUED)
            self._uow.commit()
            return ProcessTaskResult(task_id=task_id, outcome="deferred_active_run")

        if not parsed.ok or parsed.asset is None:
            self._commit_failure(task_id, resource.id, task.owner_import_run_id, parsed)
            self._queue.complete("import", task_id)
            self._uow.commit()
            return ProcessTaskResult(task_id=task_id, outcome="failed")

        published_run_id = task.owner_import_run_id or resource.published_run_id
        if published_run_id is None:
            published_run_id = task.owner_import_run_id
        if published_run_id is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary="missing_published_run",
            )
            self._uow.commit()
            return ProcessTaskResult(task_id=task_id, outcome="missing_published_run")

        if task.owner_import_run_id is not None:
            self._import_runs.upsert_asset_candidate(
                import_run_id=task.owner_import_run_id,
                library_id=resource.library_id,
                source_node_id=task.source_node_id,
                role=parsed.asset.role,
                import_state=AssetImportState.READY,
                sequence_index=parsed.asset.sequence_index,
                sort_key=parsed.asset.sort_key,
                failure_reason=None,
            )

        already_ready = resource.import_state is ResourceImportState.READY
        if not already_ready:
            self._books_resources.publish_resource(
                resource_id=resource.id,
                published_run_id=published_run_id,
                adapter=adapter,
                title=parsed.resource_title or node.name,
            )
            self._books_resources.upsert_asset(
                library_id=resource.library_id,
                resource_id=resource.id,
                source_node_id=task.source_node_id,
                published_run_id=published_run_id,
                role=parsed.asset.role,
                import_state=AssetImportState.READY,
                sequence_index=parsed.asset.sequence_index,
                sort_key=parsed.asset.sort_key,
                failure_reason=None,
            )
        else:
            self._books_resources.upsert_asset(
                library_id=resource.library_id,
                resource_id=resource.id,
                source_node_id=task.source_node_id,
                published_run_id=resource.published_run_id or published_run_id,
                role=parsed.asset.role,
                import_state=AssetImportState.READY,
                sequence_index=parsed.asset.sequence_index,
                sort_key=parsed.asset.sort_key,
                failure_reason=None,
            )

        ready_count = self._books_resources.count_ready_assets_for_published_run(
            resource.id,
            resource.published_run_id or published_run_id,
        )
        if meets_minimum_ready_assets(
            ready_asset_count=ready_count,
            minimum_ready_assets=adapter.minimum_ready_assets,
        ) and resource.import_state is not ResourceImportState.READY:
            self._books_resources.publish_resource(
                resource_id=resource.id,
                published_run_id=published_run_id,
                adapter=adapter,
                title=parsed.resource_title or node.name,
            )

        self._import_runs.mark_task_state(task_id, LibraryImportTaskState.SUCCEEDED)
        self._queue.complete("import", task_id)
        self._uow.commit()
        self._sidecar.schedule_after_commit(resource.id)
        self._log.emit(
            "readable_resource.task.succeeded",
            library_id=resource.library_id,
            resource_id=resource.id,
            run_id=task.owner_import_run_id,
            task_id=task_id,
            stage="import",
            outcome="ok",
        )
        return ProcessTaskResult(task_id=task_id, outcome="ok")

    def _commit_failure(
        self,
        task_id: str,
        resource_id: str,
        owner_run_id: str | None,
        parsed: FileParseResult,
    ) -> None:
        self._import_runs.mark_task_state(
            task_id,
            LibraryImportTaskState.FAILED,
            error_summary=parsed.error_summary or parsed.error_code,
        )
        resource = self._books_resources.get_resource(resource_id)
        if resource is None:
            return
        if (
            owner_run_id is not None
            and resource.active_import_run_id == owner_run_id
            and resource.import_state is not ResourceImportState.READY
        ):
            self._books_resources.mark_resource_failed(resource_id)
            self._books_resources.clear_active_import_run(resource_id)
            self._import_runs.set_run_state(
                owner_run_id,
                finalize_run_state(
                    published=False,
                    had_task_failures=True,
                    cancelled=False,
                    reached_minimum_ready=False,
                ),
                error_summary=parsed.error_summary,
            )
