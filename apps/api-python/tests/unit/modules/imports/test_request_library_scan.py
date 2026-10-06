from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest

from app.modules.imports.application.library_scan_settings import (
    LibraryScanSettingsRepositoryPort,
)
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
from app.modules.imports.domain.library_scan_schedule import LibraryScanSettings
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope


class _Libraries:
    def get_library(self, library_id: str) -> object:
        if library_id != "library":
            raise LookupError(library_id)
        return object()


class _Queue:
    def __init__(self) -> None:
        self.requested_policies: list[MissingEntryPolicy] = []
        self.active = False

    def has_active_tasks(self, library_id: str) -> bool:
        return self.active

    def request_library_scan(
        self,
        library_id: str,
        *,
        missing_entry_policy: MissingEntryPolicy,
        scan_scopes: tuple[ScanScope, ...] | None = None,
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


class _Settings:
    def __init__(self, interval: int = 1440) -> None:
        self.interval = interval

    def load(self) -> LibraryScanSettings:
        return LibraryScanSettings(interval_minutes=self.interval)


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
        scan_settings=cast(LibraryScanSettingsRepositoryPort, _Settings()),
    )
    use_case.execute(RequestLibraryScanCommand(library_id="library", trigger=trigger))
    assert queue.requested_policies == [MissingEntryPolicy.PRUNE_MISSING]


def test_manual_scan_only_changes_the_missing_entry_policy() -> None:
    queue = _Queue()
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
        scan_settings=cast(LibraryScanSettingsRepositoryPort, _Settings()),
    )
    use_case.execute(RequestLibraryScanCommand(library_id="library", trigger="MANUAL"))
    assert queue.requested_policies == [MissingEntryPolicy.PRUNE_MISSING]


@pytest.mark.parametrize("trigger", ["PERIODIC", "STARTUP"])
@pytest.mark.parametrize("active, interval", [(True, 1440), (False, 0)])
def test_scheduled_scan_skips_busy_or_disabled_library(trigger, active, interval) -> None:
    queue = _Queue()
    queue.active = active
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
        scan_settings=cast(LibraryScanSettingsRepositoryPort, _Settings(interval)),
    )
    result = use_case.execute(RequestLibraryScanCommand(library_id="library", trigger=trigger))
    assert not result.enqueued and result.task_id is None
    assert queue.requested_policies == []


@pytest.mark.parametrize("trigger", ["MANUAL", "WATCHER", "UPLOAD", "ENABLE"])
def test_explicit_or_file_event_scan_still_enqueues_when_busy_and_periodic_disabled(trigger) -> None:
    queue = _Queue()
    queue.active = True
    use_case = RequestLibraryScan(
        libraries=cast(LibraryConfigPort, _Libraries()),
        queue=cast(LibraryImportTaskQueuePort, queue),
        uow=cast(UnitOfWorkPort, _UnitOfWork()),
        log=cast(PipelineLogPort, _Log()),
        scan_settings=cast(LibraryScanSettingsRepositoryPort, _Settings(0)),
    )
    assert use_case.execute(RequestLibraryScanCommand(library_id="library", trigger=trigger)).enqueued
