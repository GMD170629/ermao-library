from __future__ import annotations

import pytest

from app.modules.imports.domain.import_run_policies import (
    ImportRunState,
    finalize_run_state,
    import_run_is_nonterminal,
    import_run_is_terminal,
    may_commit_incremental_result,
    may_commit_run_owned_result,
)


def test_may_commit_run_owned_requires_matching_active_run() -> None:
    assert (
        may_commit_run_owned_result(
            resource_active_import_run_id="run-1",
            task_owner_import_run_id="run-1",
        )
        is True
    )
    assert (
        may_commit_run_owned_result(
            resource_active_import_run_id="run-1",
            task_owner_import_run_id="run-2",
        )
        is False
    )
    assert (
        may_commit_run_owned_result(
            resource_active_import_run_id=None,
            task_owner_import_run_id="run-1",
        )
        is False
    )
    assert (
        may_commit_run_owned_result(
            resource_active_import_run_id="run-1",
            task_owner_import_run_id=None,
        )
        is False
    )


def test_may_commit_incremental_only_when_no_active_run() -> None:
    assert (
        may_commit_incremental_result(
            resource_active_import_run_id=None,
            task_owner_import_run_id=None,
        )
        is True
    )
    assert (
        may_commit_incremental_result(
            resource_active_import_run_id="run-1",
            task_owner_import_run_id=None,
        )
        is False
    )
    assert (
        may_commit_incremental_result(
            resource_active_import_run_id=None,
            task_owner_import_run_id="run-1",
        )
        is False
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    (
        (
            {
                "published": False,
                "had_task_failures": False,
                "cancelled": True,
                "reached_minimum_ready": False,
            },
            ImportRunState.CANCELLED,
        ),
        (
            {
                "published": False,
                "had_task_failures": True,
                "cancelled": False,
                "reached_minimum_ready": False,
            },
            ImportRunState.FAILED,
        ),
        (
            {
                "published": True,
                "had_task_failures": True,
                "cancelled": False,
                "reached_minimum_ready": True,
            },
            ImportRunState.COMPLETED_WITH_ERRORS,
        ),
        (
            {
                "published": True,
                "had_task_failures": False,
                "cancelled": False,
                "reached_minimum_ready": True,
            },
            ImportRunState.COMPLETED,
        ),
        (
            {
                "published": True,
                "had_task_failures": False,
                "cancelled": True,
                "reached_minimum_ready": True,
            },
            ImportRunState.COMPLETED,
        ),
    ),
)
def test_finalize_run_state(
    kwargs: dict[str, bool],
    expected: ImportRunState,
) -> None:
    assert finalize_run_state(**kwargs) is expected


def test_terminal_and_nonterminal_partition() -> None:
    assert import_run_is_nonterminal(ImportRunState.PENDING)
    assert import_run_is_nonterminal(ImportRunState.RUNNING)
    assert import_run_is_terminal(ImportRunState.COMPLETED)
    assert import_run_is_terminal(ImportRunState.FAILED)
    assert not import_run_is_terminal(ImportRunState.RUNNING)
