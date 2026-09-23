"""Exercise the Book task migration on a temporary pre-0031 library.

Run from the repository root with:
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python \
    -m tests.support.book_scope_upgrade_probe --books 100000
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models import Library
from app.modules.library.public import SourceNodeRelativePath

_NOW = datetime(2026, 9, 23, tzinfo=UTC)
_TIMESTAMP = int(_NOW.timestamp() * 1000)
_REVISION = "0030_book_import_task_shape"


def run(book_count: int, *, kill_during_upgrade: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="ermao-upgrade-scale-") as directory:
        root = Path(directory)
        settings = Settings(storage_root=str(root / "storage"))
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_sqlite_engine(settings.database_path)
        config = alembic_config_for_engine(engine)
        command.upgrade(config, _REVISION)
        with Session(engine) as session:
            session.add(
                Library(
                    id="scale-library",
                    name="Upgrade scale",
                    root_path=str(root / "books"),
                    organization_mode="FLAT",
                )
            )
            session.commit()
            tables = {
                name: sa.Table(name, sa.MetaData(), autoload_with=engine)
                for name in (
                    "LibrarySourceNode",
                    "LibraryBook",
                    "LibraryBookMetadata",
                    "LibraryReadableResource",
                    "LibraryResourceAsset",
                    "LibraryImportTask",
                    "LibraryImportScanGap",
                )
            }
            for start in range(0, book_count, 1000):
                rows: dict[str, list[dict[str, object]]] = {
                    name: [] for name in tables if name != "LibraryImportScanGap"
                }
                for index in range(start, min(start + 1000, book_count)):
                    suffix = f"{index:06d}"
                    node_id = f"source-{suffix}"
                    book_id = f"book-{suffix}"
                    resource_id = f"resource-{suffix}"
                    name = f"book-{suffix}.epub"
                    rows["LibrarySourceNode"].append(
                        {
                            "id": node_id,
                            "libraryId": "scale-library",
                            "relativePath": name,
                            "pathKey": SourceNodeRelativePath(name).path_key,
                            "name": name,
                            "physicalKind": "REGULAR_FILE",
                            "observedSizeBytes": 1,
                            "observedMtimeNs": 1,
                            "observedAt": _TIMESTAMP,
                            "createdAt": _TIMESTAMP,
                            "updatedAt": _TIMESTAMP,
                        }
                    )
                    rows["LibraryBook"].append(
                        {
                            "id": book_id,
                            "libraryId": "scale-library",
                            "sourceNodeId": node_id,
                            "createdAt": _TIMESTAMP,
                            "updatedAt": _TIMESTAMP,
                        }
                    )
                    rows["LibraryBookMetadata"].append(
                        {
                            "bookId": book_id,
                            "title": name,
                            "normalizedTitle": name,
                            "importRevision": 1,
                            "processedRevision": 0 if index % 1000 == 0 else 1,
                            "metadataPending": index % 1000 == 0,
                            "metadataState": "WAITING_IMPORT"
                            if index % 1000 == 0
                            else "COMPLETED",
                            "createdAt": _TIMESTAMP,
                            "updatedAt": _TIMESTAMP,
                        }
                    )
                    rows["LibraryReadableResource"].append(
                        {
                            "id": resource_id,
                            "libraryId": "scale-library",
                            "bookId": book_id,
                            "sourceNodeId": node_id,
                            "adapterId": "epub",
                            "adapterVersion": "1",
                            "format": "EPUB",
                            "createdAt": _TIMESTAMP,
                            "updatedAt": _TIMESTAMP,
                        }
                    )
                    rows["LibraryResourceAsset"].append(
                        {
                            "id": f"asset-{suffix}",
                            "libraryId": "scale-library",
                            "resourceId": resource_id,
                            "sourceNodeId": node_id,
                            "sourceNodePhysicalKind": "REGULAR_FILE",
                            "role": "PRIMARY",
                            "importState": "READY",
                            "processedSourceVersion": "pre-upgrade-version",
                            "createdAt": _TIMESTAMP,
                            "updatedAt": _TIMESTAMP,
                        }
                    )
                    if index % 100 == 0:
                        state = ("QUEUED", "FAILED", "RUNNING", "SUCCEEDED")[
                            (index // 100) % 4
                        ]
                        rows["LibraryImportTask"].append(
                            {
                                "id": f"old-task-{suffix}",
                                "kind": "IMPORT_RESOURCE",
                                "libraryId": "scale-library",
                                "sourceNodeId": node_id,
                                "resourceId": resource_id,
                                "resourceAnchorNodeId": node_id,
                                "state": state,
                                "errorSummary": "OLD_FAILURE"
                                if state == "FAILED"
                                else None,
                                "createdAt": _TIMESTAMP,
                            }
                        )
                for table_name, batch in rows.items():
                    if batch:
                        session.execute(tables[table_name].insert(), batch)
                session.commit()
            session.execute(
                tables["LibraryImportScanGap"]
                .insert()
                .values(
                    libraryId="scale-library",
                    scopes='[{"relativePath":"missing","recursive":true}]',
                )
            )
            session.commit()
        if kill_during_upgrade:
            child = r'''
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from alembic import command
from sqlalchemy import event
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
engine = create_sqlite_engine(Path(sys.argv[1]))
def terminate_after_book_insert(_connection, _cursor, statement, parameters, _context, _many):
    if 'LibraryImportTask' in statement and statement.lstrip().upper().startswith('INSERT') and 'IMPORT_BOOK' in str(parameters):
        os._exit(23)
event.listen(engine, 'after_cursor_execute', terminate_after_book_insert)
with engine.connect() as connection:
    config = alembic_config_for_engine(engine)
    config.attributes['connection'] = connection
    command.upgrade(config, 'head')
os._exit(99)
'''
            interrupted = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(settings.database_path),
                    str(Path(__file__).resolve().parents[2]),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert interrupted.returncode == 23, (
                interrupted.returncode,
                interrupted.stdout,
                interrupted.stderr,
            )
        started = time.perf_counter()
        tracemalloc.start()
        try:
            command.upgrade(config, "head")
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        upgrade_seconds = time.perf_counter() - started
        with engine.connect() as connection:
            counts = {
                name: connection.scalar(
                    sa.select(sa.func.count()).select_from(
                        sa.Table(name, sa.MetaData(), autoload_with=connection)
                    )
                )
                for name in (
                    "LibrarySourceNode",
                    "LibraryBook",
                    "LibraryBookMetadata",
                    "LibraryReadableResource",
                    "LibraryResourceAsset",
                )
            }
            book_tasks = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM LibraryImportTask WHERE kind='IMPORT_BOOK'"
                )
            )
            mapped = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM LibraryImportTask WHERE supersededByTaskId IS NOT NULL"
                )
            )
            preserved = connection.scalar(
                sa.text(
                    "SELECT count(*) FROM LibraryResourceAsset WHERE processedSourceVersion='pre-upgrade-version'"
                )
            )
            gap = connection.scalar(
                sa.text(
                    "SELECT scopes FROM LibraryImportScanGap WHERE libraryId='scale-library'"
                )
            )
            version = connection.scalar(
                sa.text("SELECT version_num FROM alembic_version")
            )
            for index in (0, book_count // 2, book_count - 1):
                suffix = f"{index:06d}"
                assert connection.scalar(
                    sa.text("SELECT sourceNodeId FROM LibraryBook WHERE id=:book_id"),
                    {"book_id": f"book-{suffix}"},
                ) == f"source-{suffix}"
                assert connection.execute(
                    sa.text(
                        "SELECT resourceId, processedSourceVersion "
                        "FROM LibraryResourceAsset WHERE id=:asset_id"
                    ),
                    {"asset_id": f"asset-{suffix}"},
                ).one() == (f"resource-{suffix}", "pre-upgrade-version")
            for index, state in ((0, "QUEUED"), (100, "FAILED"), (200, "RUNNING"), (300, "SUCCEEDED")):
                if index >= book_count:
                    continue
                old_state, destination = connection.execute(
                    sa.text(
                        "SELECT state, supersededByTaskId FROM LibraryImportTask "
                        "WHERE id=:task_id"
                    ),
                    {"task_id": f"old-task-{index:06d}"},
                ).one()
                assert old_state == state
                assert (destination is not None) is (state != "SUCCEEDED")
        assert all(value == book_count for value in counts.values()), counts
        assert preserved == book_count
        assert mapped == book_count // 100 - book_count // 400
        assert book_tasks == mapped
        assert gap == '[{"relativePath":"missing","recursive":true}]'
        assert version == "0033_book_scan_gate"
        print(
            json.dumps(
                {
                    "books": book_count,
                    "upgrade_seconds": upgrade_seconds,
                    "peak_traced_bytes": peak_bytes,
                    "book_tasks": book_tasks,
                    "mapped_old_tasks": mapped,
                    "preserved_assets": preserved,
                    "database_bytes": settings.database_path.stat().st_size,
                    "killed_upgrade_process": kill_during_upgrade,
                }
            ),
            flush=True,
        )
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", type=int, default=100000)
    parser.add_argument("--kill-during-upgrade", action="store_true")
    arguments = parser.parse_args()
    if arguments.books < 1000 or arguments.books % 1000:
        parser.error("--books must be a multiple of 1000")
    run(arguments.books, kill_during_upgrade=arguments.kill_during_upgrade)
