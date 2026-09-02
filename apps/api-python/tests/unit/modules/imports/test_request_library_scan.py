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
from app.modules.imports.domain.scan_policy import MissingEntryPolicy


class _Libraries:
    def get_library(self, library_id: str) -> object:
        if library_id != "library":
            raise LookupError(library_id)
        return object()


class _Queue:
    def __init__(self) -> None:
        self.requested_policies: list[MissingEntryPolicy] = []

    def request_library_scan(
        self,
        library_id: str,
        *,
        missing_entry_policy: MissingEntryPolicy,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        self.requested_policies.append(missing_entry_policy)
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
                missing_entry_policy=missing_entry_policy,
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
    use_case.execute(RequestLibraryScanCommand(library_id="library", trigger=trigger))
    assert queue.requested_policies == [MissingEntryPolicy.PRESERVE]


def test_manual_scan_only_changes_the_missing_entry_policy() -> None:
    queue = _Queue()
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
    )
    use_case.execute(RequestLibraryScanCommand(library_id="library", trigger="MANUAL"))
    assert queue.requested_policies == [MissingEntryPolicy.PRUNE_MISSING]
