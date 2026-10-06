"""Scan admission upgrade clears only unfinished pre-upgrade library scans."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library, LibraryBook, LibrarySourceNode
from app.models.settings import SystemSetting
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportScanGap,
)
from app.modules.library.public import SourceNodeRelativePath


def _schema_snapshot(engine: sa.Engine) -> dict[str, object]:
    inspector = sa.inspect(engine)
    snapshot: dict[str, object] = {}
    for table in inspector.get_table_names():
        snapshot[table] = {
            "columns": [
                {**column, "type": str(column["type"])}
                for column in inspector.get_columns(table)
            ],
            "indexes": [
                {
                    **index,
                    "dialect_options": {
                        name: str(value)
                        for name, value in index.get("dialect_options", {}).items()
                    },
                }
                for index in inspector.get_indexes(table)
            ],
            "checks": inspector.get_check_constraints(table),
            "foreign_keys": inspector.get_foreign_keys(table),
            "primary_key": inspector.get_pk_constraint(table),
            "unique_constraints": inspector.get_unique_constraints(table),
        }
    return snapshot


@pytest.mark.parametrize("interrupted_stage", [None, "cleanup", "setting"])
def test_upgrade_clears_only_unfinished_library_scans(
    tmp_path: Path, interrupted_stage: str | None,
) -> None:
    engine = create_sqlite_engine(tmp_path / "upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    now = datetime(2026, 10, 6, tzinfo=UTC)
    try:
        command.upgrade(config, "0039_generated_metadata_fields")
        with Session(engine) as db:
            db.add(Library(
                id="library", name="Library", root_path=str(tmp_path / "books"),
                organization_mode="FLAT",
            ))
            db.add(LibrarySourceNode(
                id="node", library_id="library", relative_path="book.epub",
                path_key=SourceNodeRelativePath("book.epub").path_key,
                name="book.epub", physical_kind="REGULAR_FILE",
                observed_size_bytes=1, observed_mtime_ns=1, observed_at=now,
            ))
            db.flush()
            db.add(LibraryBook(id="book", library_id="library", source_node_id="node"))
            db.add(LibraryImportScanGap(library_id="library", scopes=None))
            db.add(SystemSetting(
                key="libraryScan.intervalMinutes", value="30",
                created_at=now, updated_at=now,
            ))
            db.commit()

        historical = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            for kind in ("SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_BOOK"):
                for state in ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED"):
                    values = {
                        "id": f"{kind}-{state}", "kind": kind,
                        "libraryId": "library", "state": state,
                    }
                    if kind != "SCAN_LIBRARY":
                        values["sourceNodeId"] = "node"
                    if kind == "IMPORT_BOOK":
                        values.update({
                            "bookId": "book", "phase": "IDENTIFY",
                            "bookWork": '{"scanScopes":[],"resourceIds":[],"identify":true,"reasons":[]}',
                        })
                    connection.execute(sa.insert(historical).values(values))
            before = {
                row["id"]: dict(row)
                for row in connection.execute(sa.select(historical)).mappings()
            }

        schema_before = _schema_snapshot(engine)

        if interrupted_stage:
            def fail_cleanup(_connection, statement, *_args):
                if (
                    interrupted_stage == "cleanup"
                    and isinstance(statement, sa.sql.dml.Delete)
                    and statement.table.name == "LibraryImportTask"
                ) or (
                    interrupted_stage == "setting"
                    and isinstance(statement, sa.sql.dml.Update)
                    and statement.table.name == "SystemSetting"
                ):
                    raise RuntimeError("interrupted scan cleanup")

            with engine.connect() as connection:
                config.attributes["connection"] = connection
                sa.event.listen(connection, "before_execute", fail_cleanup)
                try:
                    with pytest.raises(RuntimeError, match="interrupted scan cleanup"):
                        command.upgrade(config, "head")
                finally:
                    sa.event.remove(connection, "before_execute", fail_cleanup)
                    config.attributes.pop("connection")
            with engine.connect() as connection:
                assert MigrationContext.configure(connection).get_current_revision() == (
                    "0039_generated_metadata_fields"
                )
                assert {
                    row["id"]: dict(row)
                    for row in connection.execute(sa.select(historical)).mappings()
                } == before
            with Session(engine) as db:
                assert db.get(SystemSetting, "libraryScan.intervalMinutes").value == "30"
            assert _schema_snapshot(engine) == schema_before

        command.upgrade(config, "head")
        assert _schema_snapshot(engine) == schema_before
        current = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            after = {
                row["id"]: dict(row)
                for row in connection.execute(sa.select(current)).mappings()
            }
        assert set(after) == set(before) - {"SCAN_LIBRARY-QUEUED", "SCAN_LIBRARY-RUNNING"}
        for task_id, row in after.items():
            assert row == before[task_id]
        with Session(engine) as db:
            assert db.get(Library, "library") is not None
            assert db.get(LibraryBook, "book") is not None
            assert db.get(LibrarySourceNode, "node") is not None
            assert db.get(LibraryImportScanGap, "library") is not None
            assert db.get(SystemSetting, "libraryScan.intervalMinutes").value == "1440"

        # Repeated startup at the new head must not clear newly accepted work.
        with engine.begin() as connection:
            connection.execute(sa.insert(current).values(
                id="new-scan", kind="SCAN_LIBRARY", libraryId="library",
                state="QUEUED",
            ))
        command.upgrade(config, "head")
        assert _schema_snapshot(engine) == schema_before
        with engine.connect() as connection:
            new_scan = connection.execute(
                sa.select(current).where(current.c.id == "new-scan")
            ).mappings().one()
            assert new_scan["state"] == "QUEUED"
    finally:
        engine.dispose()


@pytest.mark.parametrize("stored_value", [None, "0", "5", "30", "60", "1440"])
def test_upgrade_normalizes_only_existing_enabled_scan_setting(
    tmp_path: Path, stored_value: str | None,
) -> None:
    engine = create_sqlite_engine(tmp_path / "settings-upgrade.sqlite3")
    config = alembic_config_for_engine(engine)
    now = datetime(2026, 10, 6, tzinfo=UTC)
    try:
        command.upgrade(config, "0039_generated_metadata_fields")
        with Session(engine) as db:
            for key, value in (
                ("libraryScan.watchEnabled", "false"),
                ("unrelated.setting", '{"value":30}'),
            ):
                db.add(SystemSetting(
                    key=key, value=value, created_at=now, updated_at=now,
                ))
            if stored_value is not None:
                db.add(SystemSetting(
                    key="libraryScan.intervalMinutes", value=stored_value,
                    created_at=now, updated_at=now,
                ))
            db.commit()
        settings = sa.Table("SystemSetting", sa.MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            before = {
                row["key"]: dict(row)
                for row in connection.execute(sa.select(settings)).mappings()
            }
        schema_before = _schema_snapshot(engine)

        command.upgrade(config, "head")
        command.upgrade(config, "head")

        assert _schema_snapshot(engine) == schema_before
        with engine.connect() as connection:
            after = {
                row["key"]: dict(row)
                for row in connection.execute(sa.select(settings)).mappings()
            }
        expected = {key: dict(row) for key, row in before.items()}
        if stored_value not in (None, "0"):
            expected["libraryScan.intervalMinutes"]["value"] = "1440"
        assert after == expected
        if stored_value is not None:
            assert json.loads(after["libraryScan.intervalMinutes"]["value"]) == (
                0 if stored_value == "0" else 1440
            )
    finally:
        engine.dispose()
