"""SQLAlchemy ImportRun / candidate / LibraryImportTask repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.common import cuid
from app.modules.imports.application.readable_resource.ports import (
    AssetCandidateRecord,
    ImportRunRecord,
    ImportRunRepositoryPort,
    LibraryImportTaskRecord,
    ResourceCandidateRecord,
)
from app.modules.imports.domain.import_run_policies import (
    ImportRunKind,
    ImportRunState,
    LibraryImportTaskState,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    AssetCandidate,
    LibraryImportRun,
    LibraryImportTask,
    ResourceCandidate,
)

_INCOMPLETE_TASK_STATES = (
    LibraryImportTaskState.QUEUED.value,
    LibraryImportTaskState.RUNNING.value,
)


class SqlAlchemyImportRunRepository(ImportRunRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_run(
        self,
        *,
        library_id: str,
        kind: ImportRunKind,
        source_node_id: str,
        resource_id: str | None,
        adapter_id: str | None,
        adapter_version: str | None,
    ) -> str:
        run_id = cuid()
        self._session.add(
            LibraryImportRun(
                id=run_id,
                library_id=library_id,
                kind=kind.value,
                state=ImportRunState.RUNNING.value,
                source_node_id=source_node_id,
                resource_id=resource_id,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                discovery_complete=False,
            )
        )
        self._session.flush()
        return run_id

    def get_run(self, run_id: str) -> ImportRunRecord | None:
        row = self._session.get(LibraryImportRun, run_id)
        if row is None:
            return None
        return ImportRunRecord(
            id=row.id,
            library_id=row.library_id,
            kind=ImportRunKind(row.kind),
            state=ImportRunState(row.state),
            source_node_id=row.source_node_id,
            resource_id=row.resource_id,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            discovery_complete=bool(row.discovery_complete),
        )

    def get_resource_candidate(
        self, run_id: str
    ) -> ResourceCandidateRecord | None:
        row = self._session.scalar(
            select(ResourceCandidate).where(ResourceCandidate.import_run_id == run_id)
        )
        if row is None:
            return None
        return ResourceCandidateRecord(
            import_run_id=row.import_run_id,
            library_id=row.library_id,
            book_id=row.book_id,
            source_node_id=row.source_node_id,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            media_kind=row.media_kind,
            format_label=row.format,
            title=row.title,
        )

    def mark_discovery_complete(self, run_id: str) -> None:
        row = self._session.get(LibraryImportRun, run_id)
        if row is None:
            raise LookupError(run_id)
        row.discovery_complete = True
        self._session.flush()

    def is_discovery_complete(self, run_id: str) -> bool:
        row = self._session.get(LibraryImportRun, run_id)
        if row is None:
            return False
        return bool(row.discovery_complete)

    def set_run_state(
        self,
        run_id: str,
        state: ImportRunState,
        *,
        error_summary: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        row = self._session.get(LibraryImportRun, run_id)
        if row is None:
            raise LookupError(run_id)
        row.state = state.value
        row.error_summary = error_summary
        row.published_at = published_at
        self._session.flush()

    def attach_resource(self, run_id: str, resource_id: str) -> None:
        row = self._session.get(LibraryImportRun, run_id)
        if row is None:
            raise LookupError(run_id)
        row.resource_id = resource_id
        self._session.flush()

    def upsert_resource_candidate(
        self,
        *,
        import_run_id: str,
        library_id: str,
        book_id: str | None,
        source_node_id: str,
        adapter: ResourceAdapterSpec,
        title: str | None,
    ) -> None:
        row = self._session.scalar(
            select(ResourceCandidate).where(
                ResourceCandidate.import_run_id == import_run_id
            )
        )
        if row is None:
            row = ResourceCandidate(id=cuid(), import_run_id=import_run_id)
            self._session.add(row)
        row.library_id = library_id
        row.book_id = book_id
        row.source_node_id = source_node_id
        row.adapter_id = adapter.adapter_id.value
        row.adapter_version = adapter.adapter_version
        row.media_kind = adapter.media_kind
        row.format = adapter.format_label
        row.title = title
        self._session.flush()

    def upsert_asset_candidate(
        self,
        *,
        import_run_id: str,
        library_id: str,
        source_node_id: str,
        role: AssetRole,
        import_state: AssetImportState,
        sequence_index: int | None,
        sort_key: str | None,
        failure_reason: str | None,
    ) -> None:
        row = self._session.scalar(
            select(AssetCandidate).where(
                AssetCandidate.import_run_id == import_run_id,
                AssetCandidate.source_node_id == source_node_id,
            )
        )
        if row is None:
            row = AssetCandidate(
                id=cuid(),
                import_run_id=import_run_id,
                source_node_id=source_node_id,
            )
            self._session.add(row)
        row.library_id = library_id
        row.role = role.value
        row.import_state = import_state.value
        row.sequence_index = sequence_index
        row.sort_key = sort_key
        row.failure_reason = failure_reason
        self._session.flush()

    def count_ready_asset_candidates(self, import_run_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(AssetCandidate)
                .where(
                    AssetCandidate.import_run_id == import_run_id,
                    AssetCandidate.import_state == AssetImportState.READY.value,
                )
            )
            or 0
        )

    def list_ready_asset_candidates(
        self, import_run_id: str
    ) -> tuple[AssetCandidateRecord, ...]:
        rows = self._session.scalars(
            select(AssetCandidate)
            .where(
                AssetCandidate.import_run_id == import_run_id,
                AssetCandidate.import_state == AssetImportState.READY.value,
            )
            .order_by(
                AssetCandidate.sequence_index.asc(),
                AssetCandidate.source_node_id.asc(),
            )
        ).all()
        return tuple(
            AssetCandidateRecord(
                import_run_id=row.import_run_id,
                library_id=row.library_id,
                source_node_id=row.source_node_id,
                role=AssetRole(row.role),
                import_state=AssetImportState(row.import_state),
                sequence_index=row.sequence_index,
                sort_key=row.sort_key,
                failure_reason=row.failure_reason,
            )
            for row in rows
        )

    def count_incomplete_tasks(self, owner_import_run_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(LibraryImportTask)
                .where(
                    LibraryImportTask.owner_import_run_id == owner_import_run_id,
                    LibraryImportTask.state.in_(_INCOMPLETE_TASK_STATES),
                )
            )
            or 0
        )

    def count_failed_tasks(self, owner_import_run_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(LibraryImportTask)
                .where(
                    LibraryImportTask.owner_import_run_id == owner_import_run_id,
                    LibraryImportTask.state == LibraryImportTaskState.FAILED.value,
                )
            )
            or 0
        )

    def create_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        owner_import_run_id: str | None,
        role: AssetRole,
    ) -> LibraryImportTaskRecord:
        row = LibraryImportTask(
            id=cuid(),
            library_id=library_id,
            state=LibraryImportTaskState.QUEUED.value,
            resource_id=resource_id,
            source_node_id=source_node_id,
            owner_import_run_id=owner_import_run_id,
            role=role.value,
            attempt_count=0,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_task(row)

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        return None if row is None else self._to_task(row)

    def mark_task_state(
        self,
        task_id: str,
        state: LibraryImportTaskState,
        *,
        error_summary: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        row.state = state.value
        row.error_summary = error_summary
        if increment_attempt:
            row.attempt_count += 1
        self._session.flush()

    def cleanup_run_candidates(self, run_id: str) -> None:
        self._session.execute(
            delete(ResourceCandidate).where(ResourceCandidate.import_run_id == run_id)
        )
        self._session.execute(
            delete(AssetCandidate).where(AssetCandidate.import_run_id == run_id)
        )
        self._session.flush()

    def _to_task(self, row: LibraryImportTask) -> LibraryImportTaskRecord:
        return LibraryImportTaskRecord(
            id=row.id,
            library_id=row.library_id,
            state=LibraryImportTaskState(row.state),
            resource_id=row.resource_id,
            source_node_id=row.source_node_id,
            owner_import_run_id=row.owner_import_run_id,
            role=AssetRole(row.role),
            attempt_count=row.attempt_count,
        )
