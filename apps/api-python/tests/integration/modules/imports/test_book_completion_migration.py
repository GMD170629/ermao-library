"""Upgrade terminal recovery fields without inventing historical results."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)


@pytest.mark.parametrize("partial_schema", (False, True))
def test_completion_intent_upgrade_preserves_historical_unknown_state(
    tmp_path: Path, partial_schema: bool,
) -> None:
    engine = create_sqlite_engine(tmp_path / "completion-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    try:
        command.upgrade(config, "0033_book_scan_gate")
        with Session(engine) as db:
            db.add(Library(
                id="library", name="Library", root_path=str(tmp_path / "books"),
                organization_mode="FLAT",
            ))
            db.commit()
        historical = sa.table(
            "LibraryImportTask",
            sa.column("id", sa.String), sa.column("kind", sa.String),
            sa.column("libraryId", sa.String), sa.column("state", sa.String),
        )
        with engine.begin() as connection:
            connection.execute(sa.insert(historical).values(
                id="historical-scan", kind="SCAN_LIBRARY",
                libraryId="library", state="FAILED",
            ))
            if partial_schema:
                Operations(MigrationContext.configure(connection)).add_column(
                    "LibraryImportTask",
                    sa.Column("completionOutcome", sa.String(32), nullable=True),
                )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with Session(engine) as db:
            task = db.get(LibraryImportTask, "historical-scan")
            assert task is not None and task.state == "FAILED"
            assert task.completion_outcome is None
            assert task.completion_retry_count == 0
    finally:
        engine.dispose()
