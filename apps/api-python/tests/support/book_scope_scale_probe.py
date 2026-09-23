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
import subprocess
import sys
import tempfile
import time
import tracemalloc
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, func, insert, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.base import Base
from app.db.sqlite import (
    SHORT_WRITE_LOCK_TIMEOUT_SECONDS,
    SQLITE_STATEMENT_TIMEOUT_SECONDS,
    create_sqlite_engine,
)
from app.infrastructure.file_operation_conflicts import file_operation_blocks_library
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
from app.modules.imports.domain.scan_policy import ScanScope, encode_scan_scopes
from app.modules.imports.infrastructure.readable_resource.scan_gating import (
    gap_covers_anchor,
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


def _engine(path: Path):
    return create_sqlite_engine(
        path,
        timeout_seconds=SHORT_WRITE_LOCK_TIMEOUT_SECONDS,
        statement_time_budget_seconds=SQLITE_STATEMENT_TIMEOUT_SECONDS,
    )


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


def _legacy_claim_trial(db: Session, engine) -> dict[str, object]:
    """Reproduce the pre-R2 query with the production SQLite time budget."""
    anchor = aliased(LibrarySourceNode)
    query = (
        select(LibraryImportTask)
        .join(anchor, anchor.id == LibraryImportTask.source_node_id)
        .where(
            LibraryImportTask.kind == "IMPORT_BOOK",
            LibraryImportTask.state == "QUEUED",
            LibraryImportTask.next_attempt_at <= NOW,
            ~file_operation_blocks_library(LibraryImportTask.library_id),
            or_(
                anchor.physical_kind == "REGULAR_FILE",
                LibraryImportTask.phase == "SCAN",
                ~gap_covers_anchor(LibraryImportTask.library_id, anchor),
            ),
        )
        .order_by(
            LibraryImportTask.next_attempt_at,
            LibraryImportTask.created_at,
            LibraryImportTask.id,
        )
        .limit(1)
    )
    captured: list[tuple[str, object]] = []
    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "LibraryImportScanGap" in statement:
            captured.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    started = time.perf_counter()
    interrupted = False
    try:
        db.scalar(query)
    except SQLAlchemyError as error:
        interrupted = "interrupted" in str(error).lower()
        if not interrupted:
            raise
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        event.remove(engine, "before_cursor_execute", capture)
        db.rollback()
    plan = []
    if captured:
        statement, parameters = captured[-1]
        with engine.connect() as conn:
            plan = conn.exec_driver_sql(
                "EXPLAIN QUERY PLAN " + statement, parameters
            ).all()
    return {
        "elapsed_ms": elapsed_ms,
        "budget_interrupted": interrupted,
        "sql_expands_gap_json": any("json_each" in sql for sql, _ in captured),
        "plan_gap": [row[3] for row in plan if "LibraryImportScanGap" in row[3] or "VIRTUAL TABLE" in row[3]],
    }


def _cold_process_trial(database: Path, size: int, storage: Path) -> None:
    engine = _engine(database)
    try:
        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(
                db, Settings(storage_root=str(storage))
            )
            worker = build_readable_resource_worker(pipeline)
            started = time.perf_counter()
            assert worker.process_once() == "book"
            worker_ms = (time.perf_counter() - started) * 1000
            assert (
                db.query(LibraryResourceAsset)
                .filter(
                    LibraryResourceAsset.resource_id == f"res-{size - 1:06d}"
                )
                .count()
                == 1
            )
        print(json.dumps({"worker_ms": worker_ms}), flush=True)
    finally:
        engine.dispose()


def probe(
    size: int, *, independent_gaps: bool = False, mixed_gaps: bool = False
) -> None:
    assert not mixed_gaps or independent_gaps
    with tempfile.TemporaryDirectory(prefix=f"ermao-scale-{size}-") as directory:
        engine = _engine(Path(directory) / "scale.sqlite3")
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
            parent_name = "shared" if mixed_gaps else "blocked" if not independent_gaps else None
            if parent_name is not None:
                db.add(LibrarySourceNode(
                    id=f"parent-{parent_name}", library_id="scale-library",
                    relative_path=parent_name,
                    path_key=SourceNodeRelativePath(parent_name).path_key,
                    name=parent_name, physical_kind="DIRECTORY",
                    observed_size_bytes=None, observed_mtime_ns=0,
                    observed_at=NOW,
                ))
                db.commit()
            for start in range(0, size, 1000):
                nodes = []
                books = []
                metadata = []
                resources = []
                tasks = []
                for i in range(start, min(start + 1000, size)):
                    ident = f"{i:06d}"
                    blocked = i < size - 1 if independent_gaps else i % 20 == 0
                    if not blocked:
                        name = f"book-{ident}.epub"
                    elif mixed_gaps and i < (size - 1) // 2:
                        name = f"shared/book-{ident}"
                    elif independent_gaps:
                        name = f"blocked-{ident}"
                    else:
                        name = f"blocked/book-{ident}"
                    node = f"src-{ident}"
                    book = f"book-{ident}"
                    nodes.append(
                        {
                            "id": node,
                            "library_id": "scale-library",
                            "parent_id": (
                                f"parent-{parent_name}"
                                if parent_name is not None and name.startswith(parent_name + "/")
                                else None
                            ),
                            "parent_physical_kind": (
                                "DIRECTORY"
                                if parent_name is not None and name.startswith(parent_name + "/")
                                else None
                            ),
                            "relative_path": name,
                            "path_key": SourceNodeRelativePath(name).path_key,
                            "name": name,
                            "physical_kind": (
                                "DIRECTORY" if blocked else "REGULAR_FILE"
                            ),
                            "observed_size_bytes": (
                                None
                                if blocked
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
                            "adapter_id": "image_dir" if blocked else "epub",
                            "adapter_version": "1",
                            "format": "IMAGE_DIR" if blocked else "EPUB",
                        }
                    )
                    if independent_gaps and blocked or not independent_gaps and i % 2 == 0:
                        state = (
                            "QUEUED"
                            if blocked
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
                                "book_work": encode_book_work(BookWorkState(pending=BookWork(identify=True))),
                                "scan_gate_blocked": blocked,
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
                                "scan_gate_blocked": False,
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
                    scopes=encode_scan_scopes(
                        ((ScanScope("shared", True),) if mixed_gaps else ())
                        + tuple(
                            ScanScope(f"blocked-{i:06d}", True)
                            for i in range((size - 1) // 2 if mixed_gaps else 0, size - 1)
                        )
                    ) if independent_gaps else '[{"relativePath":"blocked","recursive":true}]',
                )
            )
            db.commit()
            target = f"book-{size - 1:06d}"
            queue = SqlAlchemyLibraryImportTaskQueue(db)
            request = queue.request_book_work(
                book_id=target, work=BookWork(identify=True), requested_at=NOW
            )
            db.commit()
            legacy = _legacy_claim_trial(db, engine) if independent_gaps else None
            no_runnable_times: list[float] = []
            if independent_gaps:
                db.execute(update(LibraryImportTask).where(
                    LibraryImportTask.id == request.id
                ).values(next_attempt_at=LATER))
                db.commit()
                for _ in range(6):
                    started = time.perf_counter()
                    assert queue.claim_next_book(started_at=NOW) is None
                    no_runnable_times.append((time.perf_counter() - started) * 1000)
                    db.rollback()
                db.execute(update(LibraryImportTask).where(
                    LibraryImportTask.id == request.id
                ).values(next_attempt_at=NOW))
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
                closing(sqlite3.connect(engine.url.database)) as original,
                closing(sqlite3.connect(snapshot)) as saved,
            ):
                original.backup(saved)
            cold_path = Path(directory) / "cold-trial.sqlite3"
            shutil.copy2(snapshot, cold_path)
            started = time.perf_counter()
            cold_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.support.book_scope_scale_probe",
                    "--cold-trial",
                    str(cold_path),
                    str(size),
                    str(Path(directory) / "storage-cold"),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            cold_process_wall_ms = (time.perf_counter() - started) * 1000
            cold_worker_ms = json.loads(cold_result.stdout.splitlines()[-1])[
                "worker_ms"
            ]
            full_times = []
            local_scan_times = []
            stage_times: list[dict[str, float]] = []
            for trial in range(6):
                trial_path = Path(directory) / f"trial-{trial}.sqlite3"
                shutil.copy2(snapshot, trial_path)
                trial_engine = _engine(trial_path)
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
                            pipeline.adapters,
                            "parse_file",
                            _timed(stage, "parse_media", pipeline.adapters.parse_file),
                        ),
                        patch.object(
                            pipeline.process_import_task,
                            "save_asset_result",
                            _timed(
                                stage,
                                "save_asset",
                                pipeline.process_import_task.save_asset_result,
                            ),
                        ),
                        patch.object(
                            pipeline.process_import_task,
                            "finalize_resource",
                            _timed(
                                stage,
                                "finalize_resource",
                                pipeline.process_import_task.finalize_resource,
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
                    started = time.perf_counter()
                    scan = pipeline.scan_library_source_tree.execute_source(
                        f"src-{size - 1:06d}"
                    )
                    local_scan_times.append((time.perf_counter() - started) * 1000)
                    assert scan.resources_created == 0
                    assert scan.tasks_enqueued == 0
                trial_engine.dispose()
            memory_path = Path(directory) / "memory-trial.sqlite3"
            shutil.copy2(snapshot, memory_path)
            memory_engine = _engine(memory_path)
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
                worker_sql = dict(sql)
                worker_epub_opens = file_opens
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
                    scan = pipeline.scan_library_source_tree.execute_source(
                        f"src-{size - 1:06d}"
                    )
                assert scan.resources_created == 0
                assert scan.tasks_enqueued == 0
                local_scan_sql = {
                    key: sql[key] - worker_sql[key] for key in worker_sql
                }
                local_scan_epub_opens = file_opens - worker_epub_opens
            memory_engine.dispose()
            print(
                "FULL", size, full_times, statistics.median(full_times[1:]), flush=True
            )
            print(
                json.dumps(
                    {
                        "books": size,
                        "gap_mode": (
                            "mixed" if mixed_gaps else
                            "independent" if independent_gaps else "shared"
                        ),
                        "tasks": size if independent_gaps else size * 3 // 4 + 1,
                        "independent_gaps": (
                            size - 1 - ((size - 1) // 2 if mixed_gaps else 0)
                            if independent_gaps else 0
                        ),
                        "no_runnable_warm_median_ms": (
                            statistics.median(no_runnable_times[1:])
                            if no_runnable_times else None
                        ),
                        "legacy_claim": legacy,
                        "claim_ms": times,
                        "claim_warm_median_ms": statistics.median(times[1:]),
                        "finish_ms": finish,
                        "finish_warm_median_ms": statistics.median(finish[1:]),
                        "worker_warm_median_ms": statistics.median(full_times[1:]),
                        "fresh_process_worker_ms": cold_worker_ms,
                        "fresh_process_wall_ms": cold_process_wall_ms,
                        "unchanged_local_scan_ms": local_scan_times,
                        "unchanged_local_scan_warm_median_ms": statistics.median(
                            local_scan_times[1:]
                        ),
                        "stage_warm_median_ms": {
                            stage: statistics.median(
                                sample.get(stage, 0.0) for sample in stage_times[1:]
                            )
                            for stage in (
                                "claim",
                                "resources",
                                "parse_and_save",
                                "parse_media",
                                "save_asset",
                                "finalize_resource",
                                "identify",
                                "finish",
                            )
                        },
                        "worker_sql": worker_sql,
                        "unchanged_local_scan_sql": local_scan_sql,
                        "unchanged_local_scan_epub_opens": local_scan_epub_opens,
                        "worker_peak_traced_bytes": peak_bytes,
                        "epub_opens": worker_epub_opens,
                        "plan": [(r[0], r[3]) for r in plan],
                    }
                ),
                flush=True,
            )
        engine.dispose()


def probe_large_gate_transition(size: int = 100000) -> None:
    """Exercise one broad scan change against real queued directory Books."""
    with tempfile.TemporaryDirectory(prefix="ermao-gate-transition-") as directory:
        engine = _engine(Path(directory) / "gate.sqlite3")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(Library(
                    id="gate-library", name="Gate", root_path=directory,
                    organization_mode="FLAT",
                ))
                db.add(LibrarySourceNode(
                    id="parent-blocked", library_id="gate-library",
                    relative_path="blocked",
                    path_key=SourceNodeRelativePath("blocked").path_key,
                    name="blocked", physical_kind="DIRECTORY",
                    observed_size_bytes=None, observed_mtime_ns=0, observed_at=NOW,
                ))
                db.commit()
                pending_work = encode_book_work(BookWorkState(
                    pending=BookWork(resource_ids=None, identify=True)
                ))
                for start in range(0, size, 1000):
                    nodes = []
                    books = []
                    metadata = []
                    resources = []
                    tasks = []
                    for index in range(start, min(start + 1000, size)):
                        ident = f"{index:06d}"
                        path = f"blocked/book-{ident}"
                        node_id = f"node-{ident}"
                        book_id = f"book-{ident}"
                        nodes.append({
                            "id": node_id, "library_id": "gate-library",
                            "parent_id": "parent-blocked",
                            "parent_physical_kind": "DIRECTORY",
                            "relative_path": path,
                            "path_key": SourceNodeRelativePath(path).path_key,
                            "name": f"book-{ident}", "physical_kind": "DIRECTORY",
                            "observed_size_bytes": None, "observed_mtime_ns": 0,
                            "observed_at": NOW,
                        })
                        books.append({
                            "id": book_id, "library_id": "gate-library",
                            "source_node_id": node_id,
                        })
                        metadata.append({
                            "book_id": book_id, "title": path, "normalized_title": path,
                            "metadata_pending": True, "metadata_state": "WAITING_IMPORT",
                        })
                        resources.append({
                            "id": f"resource-{ident}", "library_id": "gate-library",
                            "book_id": book_id, "source_node_id": node_id,
                            "adapter_id": "image_dir", "adapter_version": "1",
                            "format": "IMAGE_DIR",
                        })
                        tasks.append({
                            "id": f"task-{ident}", "kind": "IMPORT_BOOK",
                            "library_id": "gate-library", "source_node_id": node_id,
                            "book_id": book_id, "state": "QUEUED", "phase": "RESOURCES",
                            "book_work": pending_work, "scan_gate_blocked": False,
                            "request_version": 1, "next_attempt_at": NOW,
                            "created_at": NOW,
                        })
                    db.execute(insert(LibrarySourceNode), nodes)
                    db.execute(insert(LibraryBook), books)
                    db.execute(insert(LibraryBookMetadata), metadata)
                    db.execute(insert(LibraryReadableResource), resources)
                    db.execute(insert(LibraryImportTask), tasks)
                    db.commit()
                queue = SqlAlchemyLibraryImportTaskQueue(db)
                started = time.perf_counter()
                queue.apply_scan_round(
                    None, "gate-library", resolved=(),
                    incomplete=(ScanScope("", True),),
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                db.commit()
                unknown = db.scalar(select(func.count()).select_from(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.scan_gate_blocked.is_(None),
                ))
                assert queue.claim_next_book(started_at=NOW) is None
                print(json.dumps({
                    "gate_transition_books": size,
                    "record_gap_ms": elapsed_ms,
                    "durable_unknown_gates": unknown,
                }), flush=True)
        finally:
            engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--cold-trial":
        _cold_process_trial(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    else:
        for count in (1000, 10000, 100000):
            probe(count)
        for count in (1001, 5001):
            probe(count, independent_gaps=True)
        probe(1001, independent_gaps=True, mixed_gaps=True)
        probe_large_gate_transition()
