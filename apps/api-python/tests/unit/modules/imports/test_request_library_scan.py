from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest

from app.modules.imports.application.readable_resource.ports import (
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    PipelineLogPort,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    LibraryScanTrigger,
    RequestLibraryScan,
    RequestLibraryScanCommand,
)


class _Libraries:
    def get_library(self, library_id: str) -> object:
        if library_id != "library":
            raise LookupError(library_id)
        return object()


class _Queue:
    def __init__(self) -> None:
        self.requeue_calls = 0

    def requeue_failed_for_library(self, library_id: str) -> int:
        assert library_id == "library"
        self.requeue_calls += 1
        return 3

    def request_library_scan(
        self, library_id: str
    ) -> tuple[LibraryImportTaskRecord, bool]:
        return (
            LibraryImportTaskRecord(
                id="task",
                kind="SCAN_LIBRARY",
                library_id=library_id,
                state="QUEUED",
                resource_id=None,
                source_node_id=None,
                role=None,
                error_summary=None,
            ),
            True,
        )


class _UnitOfWork:
    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


class _Log:
    def emit(self, _event: str, **_fields: object) -> None:
        return None


@pytest.mark.parametrize(
    "trigger",
    ["STARTUP", "WATCHER", "PERIODIC", "UPLOAD", "ENABLE"],
)
def test_automatic_scan_triggers_do_not_retry_historical_failures(
    trigger: LibraryScanTrigger,
) -> None:
    queue = _Queue()
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
    )
    result = use_case.execute(
        RequestLibraryScanCommand(library_id="library", trigger=trigger)
    )
    assert result.requeued_failed == 0
    assert queue.requeue_calls == 0


def test_manual_scan_retries_failed_resources_before_requesting_scan() -> None:
    queue = _Queue()
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
    )
    result = use_case.execute(
        RequestLibraryScanCommand(library_id="library", trigger="MANUAL")
    )
    assert result.requeued_failed == 3
    assert queue.requeue_calls == 1
