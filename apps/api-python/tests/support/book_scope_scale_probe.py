"""Run the Book claim and single EPUB import scale probe on temporary databases.

Run from the repository root with:
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python \
    -m tests.support.book_scope_scale_probe
"""

from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import sqlite3
import statistics
import tempfile
import time
import tracemalloc
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, insert, update
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
    encode_book_work,
)
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportScanGap,
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath

NOW = datetime(2026, 9, 23, tzinfo=UTC)
LATER = NOW + timedelta(days=7)


def _timed(stage: dict[str, float], label: str, operation):
    def measure(*args, **kwargs):
        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            stage[label] = stage.get(label, 0.0) + (
                time.perf_counter() - started
            ) * 1000

    return measure


def probe(size: int) -> None:
    with tempfile.TemporaryDirectory(prefix=f"ermao-scale-{size}-") as directory:
        engine = create_sqlite_engine(Path(directory) / "scale.sqlite3")
        Base.metadata.create_all(engine)
        target_file = Path(directory) / f"book-{size - 1:06d}.epub"
        with zipfile.ZipFile(target_file, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
            )
            archive.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Scale book</dc:title><dc:creator>Scale author</dc:creator></metadata><manifest><item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>',
            )
            archive.writestr("OEBPS/one.xhtml", "<html><body>Sample</body></html>")
        file_stat = target_file.stat()
        with Session(engine) as db:
            db.add(
                Library(
                    id="scale-library",
                    name="Scale",
                    root_path=directory,
                    organization_mode="FLAT",
                )
            )
            db.commit()
            for start in range(0, size, 1000):
                nodes = []
                books = []
                metadata = []
                resources = []
                tasks = []
                for i in range(start, min(start + 1000, size)):
                    ident = f"{i:06d}"
                    name = (
                        f"blocked/book-{ident}" if i % 20 == 0 else f"book-{ident}.epub"
                    )
                    node = f"src-{ident}"
                    book = f"book-{ident}"
                    nodes.append(
                        {
                            "id": node,
                            "library_id": "scale-library",
                            "relative_path": name,
                            "path_key": SourceNodeRelativePath(name).path_key,
                            "name": name,
                            "physical_kind": (
                                "DIRECTORY" if i % 20 == 0 else "REGULAR_FILE"
                            ),
                            "observed_size_bytes": (
                                None
                                if i % 20 == 0
                                else (file_stat.st_size if i == size - 1 else 1)
                            ),
                            "observed_mtime_ns": (
                                file_stat.st_mtime_ns if i == size - 1 else 1
                            ),
                            "observed_at": NOW,
                        }
                    )
                    books.append(
                        {
                            "id": book,
                            "library_id": "scale-library",
                            "source_node_id": node,
                        }
                    )
                    metadata.append(
                        {
                            "book_id": book,
                            "title": name,
                            "normalized_title": name,
                            "metadata_pending": False,
                            "metadata_state": "COMPLETED",
                            "import_revision": 1,
                            "processed_revision": 1,
                        }
                    )
                    resources.append(
                        {
                            "id": f"res-{ident}",
                            "library_id": "scale-library",
                            "book_id": book,
                            "source_node_id": node,
                            "adapter_id": "epub",
                            "adapter_version": "1",
                            "format": "EPUB",
                        }
                    )
                    if i % 2 == 0:
                        state = (
                            "QUEUED"
                            if i % 20 == 0
                            else ("SUCCEEDED" if i % 4 == 0 else "FAILED")
                        )
                        tasks.append(
                            {
                                "id": f"task-{ident}",
                                "kind": "IMPORT_BOOK",
                                "library_id": "scale-library",
                                "source_node_id": node,
                                "book_id": book,
                                "state": state,
                                "phase": "IDENTIFY",
                                "book_work": '{"active":{"scanScopes":[],"resourceIds":[],"identify":false,"reasons":[]},"pending":{"scanScopes":[],"resourceIds":[],"identify":false,"reasons":[]}}',
                                "request_version": 1,
                                "next_attempt_at": NOW,
                                "created_at": NOW - timedelta(days=1),
                            }
                        )
                    elif i % 4 == 1:
                        tasks.append(
                            {
                                "id": f"task-{ident}",
                                "kind": "IMPORT_BOOK",
                                "library_id": "scale-library",
                                "source_node_id": node,
                                "book_id": book,
                                "state": "QUEUED",
                                "phase": "IDENTIFY",
                                "book_work": '{"active":{"scanScopes":[],"resourceIds":[],"identify":false,"reasons":[]},"pending":{"scanScopes":[],"resourceIds":[],"identify":true,"reasons":[]}}',
                                "request_version": 1,
                                "next_attempt_at": LATER,
                                "created_at": NOW,
                            }
                        )
                db.execute(insert(LibrarySourceNode), nodes)
                db.execute(insert(LibraryBook), books)
                db.execute(insert(LibraryBookMetadata), metadata)
                db.execute(insert(LibraryReadableResource), resources)
                if tasks:
                    db.execute(insert(LibraryImportTask), tasks)
                db.commit()
            db.add(
                LibraryImportScanGap(
                    library_id="scale-library",
                    scopes='[{"relativePath":"blocked","recursive":true}]',
                )
            )
            db.commit()
            target = f"book-{size - 1:06d}"
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            request = queue.request_book_work(
                book_id=target, work=BookWork(identify=True), requested_at=NOW
            )
            db.commit()
            captured = []

            def capture(_conn, _cursor, statement, parameters, _context, _many):
                if (
                    statement.lstrip().upper().startswith("SELECT")
                    and "LibraryImportTask" in statement
                    and "JOIN" in statement
                ):
                    captured.append((statement, parameters))

            event.listen(engine, "before_cursor_execute", capture)
            times = []
            for j in range(6):
                t = time.perf_counter()
                claimed = queue.claim_next_book(started_at=NOW)
                times.append((time.perf_counter() - t) * 1000)
                assert claimed and claimed.id == request.id
                db.rollback()
                db.expire_all()
            event.remove(engine, "before_cursor_execute", capture)
            plan = []
            if captured:
                statement, params = captured[-1]
                with engine.connect() as conn:
                    plan = conn.exec_driver_sql(
                        "EXPLAIN QUERY PLAN " + statement, params
                    ).all()
            claimed = queue.claim_next_book(started_at=NOW)
            assert claimed and claimed.execution_version is not None
            db.execute(
                update(LibraryBookMetadata)
                .where(LibraryBookMetadata.book_id == target)
                .values(
                    metadata_pending=False,
                    processed_revision=2,
                    import_revision=2,
                    metadata_state="COMPLETED",
                )
            )
            db.commit()
            finish = []
            for j in range(6):
                t = time.perf_counter()
                result = queue.finish_book_run(
                    request.id,
                    execution_version=claimed.execution_version,
                    finished_at=NOW,
                )
                finish.append((time.perf_counter() - t) * 1000)
                assert result and result.state == "SUCCEEDED"
                db.rollback()
                db.expire_all()
            db.execute(
                update(LibraryImportTask)
                .where(LibraryImportTask.id == request.id)
                .values(
                    state="QUEUED",
                    phase="RESOURCES",
                    execution_version=None,
                    book_work=encode_book_work(
                        BookWorkState(
                            pending=BookWork(resource_ids=(f"res-{size - 1:06d}",))
                        )
                    ),
                    request_version=2,
                    next_attempt_at=NOW,
                )
            )
            db.execute(
                update(LibraryBookMetadata)
                .where(LibraryBookMetadata.book_id == target)
                .values(
                    import_revision=3,
                    processed_revision=2,
                    metadata_pending=True,
                    metadata_state="WAITING_IMPORT",
                )
            )
            db.commit()
            snapshot = Path(directory) / "snapshot.sqlite3"
            with (
                sqlite3.connect(engine.url.database) as original,
                sqlite3.connect(snapshot) as saved,
            ):
                original.backup(saved)
            full_times = []
            stage_times: list[dict[str, float]] = []
            for trial in range(6):
                trial_path = Path(directory) / f"trial-{trial}.sqlite3"
                shutil.copy2(snapshot, trial_path)
                trial_engine = create_sqlite_engine(trial_path)
                with Session(trial_engine) as trial_db:
                    pipeline = build_readable_resource_pipeline(
                        trial_db,
                        Settings(
                            storage_root=str(Path(directory) / f"storage-{trial}")
                        ),
                    )
                    worker = build_readable_resource_worker(pipeline)
                    stage: dict[str, float] = {}

                    with (
                        patch.object(
                            pipeline.queue,
                            "claim_next_book",
                            _timed(stage, "claim", pipeline.queue.claim_next_book),
                        ),
                        patch.object(
                            worker._process_book_resources,
                            "execute",
                            _timed(stage, "resources", worker._process_book_resources.execute),
                        ),
                        patch.object(
                            pipeline.process_import_task,
                            "process_resource",
                            _timed(
                                stage,
                                "parse_and_save",
                                pipeline.process_import_task.process_resource,
                            ),
                        ),
                        patch.object(
                            pipeline.identify_book,
                            "execute",
                            _timed(stage, "identify", pipeline.identify_book.execute),
                        ),
                        patch.object(
                            worker,
                            "_finish_pending_completion",
                            _timed(stage, "finish", worker._finish_pending_completion),
                        ),
                    ):
                        started = time.perf_counter()
                        outcome = worker.process_once()
                    full_times.append((time.perf_counter() - started) * 1000)
                    stage_times.append(stage)
                    assert outcome == "book", (size, trial, outcome)
                    assert (
                        trial_db.query(LibraryResourceAsset)
                        .filter(
                            LibraryResourceAsset.resource_id == f"res-{size - 1:06d}"
                        )
                        .count()
                        == 1
                    )
                trial_engine.dispose()
            memory_path = Path(directory) / "memory-trial.sqlite3"
            shutil.copy2(snapshot, memory_path)
            memory_engine = create_sqlite_engine(memory_path)
            sql = {"driver_calls": 0, "selects": 0, "commits": 0}

            def count_sql(
                _connection, _cursor, statement, _parameters, _context, _many
            ):
                sql["driver_calls"] += 1
                sql["selects"] += int(statement.lstrip().upper().startswith("SELECT"))

            def count_commit(_connection):
                sql["commits"] += 1

            event.listen(memory_engine, "before_cursor_execute", count_sql)
            event.listen(memory_engine, "commit", count_commit)
            file_opens = 0
            builtin_open = builtins.open
            io_open = io.open

            def guard_open(original, file, *args, **kwargs):
                nonlocal file_opens
                if isinstance(file, (str, bytes, os.PathLike)):
                    opened = Path(file)
                    if opened.suffix.lower() == ".epub":
                        assert opened.resolve() == target_file.resolve(), opened
                        file_opens += 1
                return original(file, *args, **kwargs)

            with Session(memory_engine) as memory_db:
                pipeline = build_readable_resource_pipeline(
                    memory_db,
                    Settings(storage_root=str(Path(directory) / "storage-memory")),
                )
                worker = build_readable_resource_worker(pipeline)
                tracemalloc.start()
                try:
                    with (
                        patch(
                            "builtins.open",
                            lambda file, *args, **kwargs: guard_open(
                                builtin_open, file, *args, **kwargs
                            ),
                        ),
                        patch(
                            "io.open",
                            lambda file, *args, **kwargs: guard_open(
                                io_open, file, *args, **kwargs
                            ),
                        ),
                    ):
                        assert worker.process_once() == "book"
                    _, peak_bytes = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
            memory_engine.dispose()
            print(
                "FULL", size, full_times, statistics.median(full_times[1:]), flush=True
            )
            print(
                json.dumps(
                    {
                        "books": size,
                        "tasks": size * 3 // 4 + 1,
                        "claim_ms": times,
                        "claim_warm_median_ms": statistics.median(times[1:]),
                        "finish_ms": finish,
                        "finish_warm_median_ms": statistics.median(finish[1:]),
                        "worker_warm_median_ms": statistics.median(full_times[1:]),
                        "stage_warm_median_ms": {
                            stage: statistics.median(
                                sample.get(stage, 0.0) for sample in stage_times[1:]
                            )
                            for stage in (
                                "claim",
                                "resources",
                                "parse_and_save",
                                "identify",
                                "finish",
                            )
                        },
                        "worker_sql": sql,
                        "worker_peak_traced_bytes": peak_bytes,
                        "epub_opens": file_opens,
                        "plan": [(r[0], r[3]) for r in plan],
                    }
                ),
                flush=True,
            )
        engine.dispose()


if __name__ == "__main__":
    for count in (1000, 10000, 100000):
        probe(count)
