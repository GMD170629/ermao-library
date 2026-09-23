"""Process the explicitly requested resources of one claimed Book task."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.application.readable_resource.ports import (
    BookImportTaskQueuePort,
    BookImportTaskRecord,
    BookResourceRepositoryPort,
    ClockPort,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)


@dataclass(frozen=True, slots=True)
class BookResourceBatchResult:
    outcome: str
    error_summary: str | None = None


@dataclass(slots=True)
class _BookResourceRun:
    queue: BookImportTaskQueuePort
    resources: BookResourceRepositoryPort
    clock: ClockPort
    operation_id: str
    book_id: str
    library_id: str
    execution_version: int
    resource_id: str
    source_node_id: str
    error_summary: str | None = None
    position_complete: bool = False

    @property
    def can_yield_directory(self) -> bool:
        return True

    def is_current(self) -> bool:
        if not self.queue.book_run_is_current(
            self.operation_id, execution_version=self.execution_version
        ):
            return False
        return self.resources.resource_matches_owner(
            resource_id=self.resource_id,
            book_id=self.book_id,
            library_id=self.library_id,
            source_node_id=self.source_node_id,
        )

    def start(self, *, started_at: datetime) -> None:
        if not self.is_current():
            raise RuntimeError("BOOK_RUN_STALE")

    def directory_cursor(self, resource_id: str) -> str | None:
        task = self.queue.get_book_task(self.operation_id)
        if task is None or task.directory_resource_id != resource_id:
            return None
        return task.directory_member_cursor

    def advance_directory_cursor(self, resource_id: str, member_id: str) -> None:
        if not self.queue.advance_directory_member_cursor(
            self.operation_id,
            execution_version=self.execution_version,
            resource_id=resource_id,
            member_id=member_id,
        ):
            raise RuntimeError("BOOK_RUN_STALE")

    def directory_cover_cursor(self, resource_id: str) -> str | None:
        task = self.queue.get_book_task(self.operation_id)
        if task is None or task.directory_resource_id != resource_id:
            return None
        return task.directory_cover_cursor

    def advance_directory_cover_cursor(self, resource_id: str, asset_id: str) -> None:
        if not self.queue.advance_directory_cover_cursor(
            self.operation_id,
            execution_version=self.execution_version,
            resource_id=resource_id,
            asset_id=asset_id,
        ):
            raise RuntimeError("BOOK_RUN_STALE")

    def request_changed(
        self, *, library_id: str, resource_id: str, source_node_id: str
    ) -> None:
        if resource_id != self.resource_id:
            raise ValueError("BOOK_RESOURCE_RUN_MISMATCH")
        self.queue.request_book_work(
            book_id=self.book_id,
            work=BookWork(resource_ids=(resource_id,)),
            requested_at=self.clock.now(),
        )

    def succeed(self, *, finished_at: datetime) -> None:
        if not self.queue.advance_book_resource_cursor(
            self.operation_id,
            execution_version=self.execution_version,
            resource_id=self.resource_id,
        ):
            raise RuntimeError("BOOK_RUN_STALE")
        self.position_complete = True

    def fail(
        self, *, error_summary: str, finished_at: datetime,
        result_persisted: bool = False,
    ) -> None:
        self.error_summary = error_summary
        if result_persisted:
            self.succeed(finished_at=finished_at)


class ProcessBookResources:
    def __init__(
        self,
        *,
        queue: BookImportTaskQueuePort,
        resources: BookResourceRepositoryPort,
        process_resource: ProcessReadableResourceImportTask,
        uow: UnitOfWorkPort,
        clock: ClockPort,
    ) -> None:
        self._queue = queue
        self._resources = resources
        self._process_resource = process_resource
        self._uow = uow
        self._clock = clock

    def failure_summary(self, book_id: str) -> str | None:
        return self._resources.book_failure_summary(book_id)

    def execute(
        self, task: BookImportTaskRecord, *, max_resources: int | None = None
    ) -> BookResourceBatchResult:
        if task.state != "RUNNING" or task.execution_version is None:
            raise ValueError("BOOK_RUN_NOT_CLAIMED")
        if max_resources is not None and max_resources < 1:
            raise ValueError("INVALID_BOOK_RESOURCE_BATCH_SIZE")
        processed = 0
        first_error: str | None = None
        for resource_id in self._resource_ids(task):
            if task.resource_cursor is not None and resource_id <= task.resource_cursor:
                continue
            if max_resources is not None and processed >= max_resources:
                return BookResourceBatchResult("yielded")
            processed += 1
            with self._uow.transaction():
                if not self._queue.book_run_is_current(
                    task.id, execution_version=task.execution_version
                ):
                    return BookResourceBatchResult("cancelled")
                resource = self._resources.get_resource(resource_id)
                if resource is None:
                    if (
                        task.work.active.resource_ids is not None
                        and not self._queue.advance_book_resource_cursor(
                            task.id,
                            execution_version=task.execution_version,
                            resource_id=resource_id,
                        )
                    ):
                        return BookResourceBatchResult("cancelled")
                    continue
                if (
                    resource.book_id != task.book_id
                    or resource.library_id != task.library_id
                ):
                    return BookResourceBatchResult("failed", "RESOURCE_OUTSIDE_BOOK")
                source_node_id = resource.source_node_id
            run = _BookResourceRun(
                queue=self._queue,
                resources=self._resources,
                clock=self._clock,
                operation_id=task.id,
                book_id=task.book_id,
                library_id=task.library_id,
                execution_version=task.execution_version,
                resource_id=resource_id,
                source_node_id=source_node_id,
            )
            result = self._process_resource.process_resource(
                library_id=task.library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                run=run,
            )
            if result.outcome == "cancelled":
                return BookResourceBatchResult("cancelled")
            if result.outcome == "yielded":
                return BookResourceBatchResult("yielded")
            if not run.position_complete:
                return BookResourceBatchResult(
                    "failed", run.error_summary or result.outcome.upper()
                )
            if run.error_summary is not None and first_error is None:
                first_error = run.error_summary
        failure_summary = self._resources.book_failure_summary(task.book_id)
        if failure_summary is not None:
            # Unreadable-file diagnostics stay on the Asset; the Book reports
            # the directory-stage failure while parser result codes stay exact.
            summary = (
                first_error
                if first_error is not None
                and failure_summary in {"IMAGE_FILE_UNREADABLE", "AUDIO_FILE_UNREADABLE"}
                else failure_summary
            )
            return BookResourceBatchResult("partial", summary)
        return BookResourceBatchResult("ok")

    def _resource_ids(self, task: BookImportTaskRecord) -> Iterator[str]:
        explicit = task.work.active.resource_ids
        if explicit is not None:
            yield from sorted(explicit)
            return
        after_id = task.resource_cursor
        while page := self._resources.page_book_resources(
            book_id=task.book_id, after_id=after_id, limit=128
        ):
            for resource in page:
                yield resource.id
            after_id = page[-1].id


__all__ = ["BookResourceBatchResult", "ProcessBookResources"]
