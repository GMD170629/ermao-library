"""Process one LibraryImportTask: parse outside txn, short txn commit + claim ack."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    adapter_identity,
    BookResourceRepositoryPort,
    ClaimedWork,
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
    ImportRunState,
    LibraryImportTaskState,
    finalize_run_state,
    may_commit_incremental_result,
    may_commit_run_owned_result,
)
from app.modules.imports.domain.resource_adapters import ADAPTER_SPECS, ResourceAdapterSpec
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    ResourceImportState,
    meets_minimum_ready_assets,
)

_DEFAULT_LEASE_SECONDS = 120


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

    def execute(
        self,
        task_id: str,
        claim: ClaimedWork,
        *,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    ) -> ProcessTaskResult:
        try:
            return self._execute(task_id, claim, lease_seconds=lease_seconds)
        except Exception:
            self._uow.rollback()
            raise

    def _execute(
        self,
        task_id: str,
        claim: ClaimedWork,
        *,
        lease_seconds: int,
    ) -> ProcessTaskResult:
        with self._uow.transaction():
            task = self._import_runs.get_task(task_id)
            if task is None:
                return ProcessTaskResult(task_id=task_id, outcome="missing_task")
            resource = self._books_resources.get_resource(task.resource_id)
            node = self._source_nodes.get(task.source_node_id)
            if resource is None or node is None:
                return ProcessTaskResult(task_id=task_id, outcome="missing_targets")
            adapter = self._resolve_adapter_for_task(task.owner_import_run_id, resource)
            if adapter is None:
                return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")
            config = self._libraries.get_library(resource.library_id)
            relative_path = node.relative_path
            root_path = config.root_path
            role = task.role
            resource_id = resource.id
            library_id = resource.library_id
            owner_run_id = task.owner_import_run_id

        self._uow.release_before_io()
        absolute = self._filesystem.resolve_under_root(root_path, relative_path)
        parsed = self._adapters.parse_file(
            absolute_path=absolute,
            adapter=adapter,
            role=role,
        )

        schedule_sidecar = False
        outcome = "ok"
        with self._uow.transaction():
            if not self._queue.fence_claim(claim, lease_seconds=lease_seconds):
                return ProcessTaskResult(task_id=task_id, outcome="late_lease")

            task = self._import_runs.get_task(task_id)
            resource = self._books_resources.get_resource(resource_id)
            node = self._source_nodes.get(task.source_node_id) if task else None
            if task is None or resource is None or node is None:
                return ProcessTaskResult(task_id=task_id, outcome="missing_targets")

            adapter = self._resolve_adapter_for_task(task.owner_import_run_id, resource)
            if adapter is None:
                self._import_runs.mark_task_state(
                    task_id,
                    LibraryImportTaskState.FAILED,
                    error_summary="unknown_adapter",
                    increment_attempt=True,
                )
                if not self._queue.complete(claim):
                    raise RuntimeError("claim_complete_failed_after_writes")
                return ProcessTaskResult(task_id=task_id, outcome="unknown_adapter")

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
                self._queue.release_and_requeue(claim)
                return ProcessTaskResult(task_id=task_id, outcome="deferred_active_run")

            if task.owner_import_run_id is not None:
                outcome = self._commit_run_owned(
                    task_id=task_id,
                    claim=claim,
                    resource_id=resource.id,
                    library_id=library_id,
                    source_node_id=task.source_node_id,
                    owner_run_id=task.owner_import_run_id,
                    node_name=node.name,
                    adapter=adapter,
                    parsed=parsed,
                )
                schedule_sidecar = outcome == "ok"
            else:
                outcome = self._commit_incremental(
                    task_id=task_id,
                    claim=claim,
                    resource_id=resource.id,
                    library_id=library_id,
                    source_node_id=task.source_node_id,
                    node_name=node.name,
                    adapter=adapter,
                    parsed=parsed,
                )
                schedule_sidecar = outcome == "ok"

        if schedule_sidecar:
            self._sidecar.schedule_after_commit(resource_id)
            self._log.emit(
                "readable_resource.task.succeeded",
                library_id=library_id,
                resource_id=resource_id,
                task_id=task_id,
                stage="import",
                outcome="ok",
            )
        return ProcessTaskResult(task_id=task_id, outcome=outcome)

    def _resolve_adapter_for_task(
        self,
        owner_import_run_id: str | None,
        resource: object,
    ) -> ResourceAdapterSpec | None:
        if owner_import_run_id is not None:
            run = self._import_runs.get_run(owner_import_run_id)
            candidate = self._import_runs.get_resource_candidate(owner_import_run_id)
            adapter_id = None
            if run is not None and run.adapter_id:
                adapter_id = run.adapter_id
            elif candidate is not None:
                adapter_id = candidate.adapter_id
            if adapter_id is not None:
                return self._resolve_adapter(adapter_id)
        adapter_id = getattr(resource, "adapter_id", None)
        if isinstance(adapter_id, str):
            return self._resolve_adapter(adapter_id)
        return None

    def _resolve_adapter(self, adapter_id: str) -> ResourceAdapterSpec | None:
        return next(
            (spec for spec in ADAPTER_SPECS if spec.adapter_id.value == adapter_id),
            None,
        )

    def _publish_adapter(
        self, owner_run_id: str, fallback: ResourceAdapterSpec
    ) -> ResourceAdapterSpec:
        candidate = self._import_runs.get_resource_candidate(owner_run_id)
        if candidate is None:
            return fallback
        resolved = self._resolve_adapter(candidate.adapter_id)
        return resolved if resolved is not None else fallback

    def _ack_or_raise(self, claim: ClaimedWork) -> None:
        if not self._queue.complete(claim):
            raise RuntimeError("claim_complete_failed_after_writes")

    def _commit_run_owned(
        self,
        *,
        task_id: str,
        claim: ClaimedWork,
        resource_id: str,
        library_id: str,
        source_node_id: str,
        owner_run_id: str,
        node_name: str,
        adapter: ResourceAdapterSpec,
        parsed: FileParseResult,
    ) -> str:
        resource = self._books_resources.get_resource(resource_id)
        if resource is None or resource.active_import_run_id != owner_run_id:
            self._import_runs.mark_task_state(task_id, LibraryImportTaskState.QUEUED)
            self._queue.release_and_requeue(claim)
            return "deferred_active_run"

        publish_adapter = self._publish_adapter(owner_run_id, adapter)

        if not parsed.ok or parsed.asset is None:
            self._import_runs.upsert_asset_candidate(
                import_run_id=owner_run_id,
                library_id=library_id,
                source_node_id=source_node_id,
                role=adapter.asset_role,
                import_state=AssetImportState.FAILED,
                sequence_index=None,
                sort_key=None,
                failure_reason=parsed.error_summary or parsed.error_code,
            )
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary=parsed.error_summary or parsed.error_code,
            )
            self._maybe_finalize_run(
                resource_id=resource_id,
                owner_run_id=owner_run_id,
                adapter=publish_adapter,
                error_summary=parsed.error_summary,
            )
            self._ack_or_raise(claim)
            return "failed"

        self._import_runs.upsert_asset_candidate(
            import_run_id=owner_run_id,
            library_id=library_id,
            source_node_id=source_node_id,
            role=parsed.asset.role,
            import_state=AssetImportState.READY,
            sequence_index=parsed.asset.sequence_index,
            sort_key=parsed.asset.sort_key,
            failure_reason=None,
        )

        resource = self._books_resources.get_resource(resource_id)
        if resource is None or resource.active_import_run_id != owner_run_id:
            self._import_runs.mark_task_state(task_id, LibraryImportTaskState.QUEUED)
            self._queue.release_and_requeue(claim)
            return "deferred_active_run"

        ready_candidates = self._import_runs.count_ready_asset_candidates(owner_run_id)
        already_published_this_run = (
            resource.import_state is ResourceImportState.READY
            and resource.published_run_id == owner_run_id
        )

        if already_published_this_run:
            self._books_resources.upsert_asset(
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                published_run_id=owner_run_id,
                role=parsed.asset.role,
                import_state=AssetImportState.READY,
                sequence_index=parsed.asset.sequence_index,
                sort_key=parsed.asset.sort_key,
                failure_reason=None,
            )
        elif meets_minimum_ready_assets(
            ready_asset_count=ready_candidates,
            minimum_ready_assets=publish_adapter.minimum_ready_assets,
        ):
            title = parsed.resource_title or node_name
            self._books_resources.publish_resource(
                resource_id=resource_id,
                published_run_id=owner_run_id,
                adapter=adapter_identity(publish_adapter),
                title=title,
            )
            for candidate in self._import_runs.list_ready_asset_candidates(owner_run_id):
                self._books_resources.upsert_asset(
                    library_id=candidate.library_id,
                    resource_id=resource_id,
                    source_node_id=candidate.source_node_id,
                    published_run_id=owner_run_id,
                    role=candidate.role,
                    import_state=AssetImportState.READY,
                    sequence_index=candidate.sequence_index,
                    sort_key=candidate.sort_key,
                    failure_reason=None,
                )
            # cleanup_stale_assets only on finalize, not first READY publish.

        self._import_runs.mark_task_state(task_id, LibraryImportTaskState.SUCCEEDED)
        self._maybe_finalize_run(
            resource_id=resource_id,
            owner_run_id=owner_run_id,
            adapter=publish_adapter,
            error_summary=None,
        )
        self._ack_or_raise(claim)
        return "ok"

    def _commit_incremental(
        self,
        *,
        task_id: str,
        claim: ClaimedWork,
        resource_id: str,
        library_id: str,
        source_node_id: str,
        node_name: str,
        adapter: ResourceAdapterSpec,
        parsed: FileParseResult,
    ) -> str:
        resource = self._books_resources.get_resource(resource_id)
        if resource is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary="resource_missing",
            )
            self._ack_or_raise(claim)
            return "missing_targets"
        if resource.active_import_run_id is not None:
            self._import_runs.mark_task_state(task_id, LibraryImportTaskState.QUEUED)
            self._queue.release_and_requeue(claim)
            return "deferred_active_run"

        published_run_id = resource.published_run_id
        if published_run_id is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary="missing_published_run",
            )
            self._ack_or_raise(claim)
            return "missing_published_run"

        if not parsed.ok or parsed.asset is None:
            self._import_runs.mark_task_state(
                task_id,
                LibraryImportTaskState.FAILED,
                error_summary=parsed.error_summary or parsed.error_code,
            )
            self._ack_or_raise(claim)
            return "failed"

        self._books_resources.upsert_asset(
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            published_run_id=published_run_id,
            role=parsed.asset.role,
            import_state=AssetImportState.READY,
            sequence_index=parsed.asset.sequence_index,
            sort_key=parsed.asset.sort_key,
            failure_reason=None,
        )
        if resource.import_state is not ResourceImportState.READY:
            self._books_resources.publish_resource(
                resource_id=resource_id,
                published_run_id=published_run_id,
                adapter=adapter_identity(adapter),
                title=parsed.resource_title or node_name,
            )
        self._import_runs.mark_task_state(task_id, LibraryImportTaskState.SUCCEEDED)
        self._ack_or_raise(claim)
        return "ok"

    def _maybe_finalize_run(
        self,
        *,
        resource_id: str,
        owner_run_id: str,
        adapter: ResourceAdapterSpec,
        error_summary: str | None,
    ) -> None:
        if not self._import_runs.is_discovery_complete(owner_run_id):
            return
        if self._import_runs.count_incomplete_tasks(owner_run_id) > 0:
            return
        resource = self._books_resources.get_resource(resource_id)
        if resource is None:
            return
        published = (
            resource.import_state is ResourceImportState.READY
            and resource.published_run_id == owner_run_id
        )
        had_failures = self._import_runs.count_failed_tasks(owner_run_id) > 0
        ready_count = self._import_runs.count_ready_asset_candidates(owner_run_id)
        if published:
            ready_count = max(
                ready_count,
                self._books_resources.count_ready_assets_for_published_run(
                    resource_id, owner_run_id
                ),
            )
        reached_minimum = meets_minimum_ready_assets(
            ready_asset_count=ready_count,
            minimum_ready_assets=adapter.minimum_ready_assets,
        )
        state = finalize_run_state(
            published=published,
            had_task_failures=had_failures,
            cancelled=False,
            reached_minimum_ready=reached_minimum,
        )
        self._import_runs.set_run_state(
            owner_run_id,
            state,
            error_summary=error_summary if state is ImportRunState.FAILED else None,
            published_at=self._clock.now() if published else None,
        )
        if resource.active_import_run_id == owner_run_id:
            self._books_resources.clear_active_import_run(resource_id)
        if not published and not reached_minimum:
            if resource.import_state is not ResourceImportState.READY:
                self._books_resources.mark_resource_failed(resource_id)
        if published:
            self._books_resources.cleanup_stale_assets(resource_id, owner_run_id)
        self._import_runs.cleanup_run_candidates(owner_run_id)
