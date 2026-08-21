"""ImportRun / ImportTask state policies for readable-resource imports."""

from __future__ import annotations

from enum import Enum


class ImportRunKind(str, Enum):
    INITIAL = "INITIAL"
    RETRY = "RETRY"
    REIMPORT = "REIMPORT"
    RECOVERY = "RECOVERY"


class ImportRunState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LibraryImportTaskState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_NONTERMINAL_RUN_STATES = frozenset(
    {ImportRunState.PENDING, ImportRunState.RUNNING}
)
_TERMINAL_RUN_STATES = frozenset(
    {
        ImportRunState.COMPLETED,
        ImportRunState.COMPLETED_WITH_ERRORS,
        ImportRunState.FAILED,
        ImportRunState.CANCELLED,
    }
)


def import_run_is_nonterminal(state: ImportRunState) -> bool:
    return state in _NONTERMINAL_RUN_STATES


def import_run_is_terminal(state: ImportRunState) -> bool:
    return state in _TERMINAL_RUN_STATES


def may_commit_run_owned_result(
    *,
    resource_active_import_run_id: str | None,
    task_owner_import_run_id: str | None,
) -> bool:
    """Run-owned results commit only while activeImportRunId matches owner."""

    if task_owner_import_run_id is None:
        return False
    return resource_active_import_run_id == task_owner_import_run_id


def may_commit_incremental_result(
    *,
    resource_active_import_run_id: str | None,
    task_owner_import_run_id: str | None,
) -> bool:
    """Incremental results commit only when no active run is present."""

    return (
        task_owner_import_run_id is None
        and resource_active_import_run_id is None
    )


def finalize_run_state(
    *,
    published: bool,
    had_task_failures: bool,
    cancelled: bool,
    reached_minimum_ready: bool,
) -> ImportRunState:
    if cancelled and not published:
        return ImportRunState.CANCELLED
    if not published and not reached_minimum_ready:
        return ImportRunState.FAILED
    if had_task_failures:
        return ImportRunState.COMPLETED_WITH_ERRORS
    return ImportRunState.COMPLETED
