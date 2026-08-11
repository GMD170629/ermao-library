from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.bootstrap.library_facet_index as migration_module
from app.bootstrap.library_facet_index import (
    LibraryFacetIndexDataMigrationError,
    run_library_facet_index_data_migration,
)
from app.modules.library.application.facet_index import FacetIndexBatchResult


class StubMigration:
    def __init__(
        self,
        outcomes: Sequence[FacetIndexBatchResult | BaseException],
    ) -> None:
        self._outcomes = iter(outcomes)
        self.limits: list[int] = []

    def execute(self, *, limit: int = 200) -> FacetIndexBatchResult:
        self.limits.append(limit)
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _install_stub(
    monkeypatch: pytest.MonkeyPatch,
    stub: StubMigration,
) -> None:
    monkeypatch.setattr(
        migration_module,
        "RebuildFacetIndexBatch",
        lambda unused_factory: stub,
    )


def test_facet_index_data_migration_runs_to_success_before_returning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = StubMigration(
        (
            FacetIndexBatchResult(processed=50, may_have_more=True),
            FacetIndexBatchResult(processed=3, may_have_more=False),
        )
    )
    _install_stub(monkeypatch, stub)

    with caplog.at_level(logging.INFO):
        run_library_facet_index_data_migration(sessionmaker[Session]())

    assert stub.limits == [50, 50]
    messages = [record.getMessage() for record in caplog.records]
    assert any("outcome=started" in message for message in messages)
    assert len([message for message in messages if "outcome=progress" in message]) == 1
    assert any("outcome=success" in message for message in messages)


def test_facet_index_data_migration_fails_when_no_progress_is_possible(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = StubMigration(
        (FacetIndexBatchResult(processed=0, may_have_more=True),)
    )
    _install_stub(monkeypatch, stub)

    with caplog.at_level(logging.INFO), pytest.raises(
        LibraryFacetIndexDataMigrationError
    ):
        run_library_facet_index_data_migration(sessionmaker[Session]())

    messages = [record.getMessage() for record in caplog.records]
    assert any("outcome=started" in message for message in messages)
    assert any("outcome=failed" in message for message in messages)
    assert not any("outcome=success" in message for message in messages)


def test_facet_index_data_migration_logs_unexpected_failure_and_blocks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = StubMigration((RuntimeError("facet write failed"),))
    _install_stub(monkeypatch, stub)

    with caplog.at_level(logging.INFO), pytest.raises(
        RuntimeError,
        match="facet write failed",
    ):
        run_library_facet_index_data_migration(sessionmaker[Session]())

    assert any(
        "outcome=failed" in record.getMessage() for record in caplog.records
    )
