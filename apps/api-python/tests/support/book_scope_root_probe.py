"""Exercise real root discovery and optional full import with 100k EPUB paths.

Run from the repository root:
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python \
    -m tests.support.book_scope_root_probe --books 100000 --drain

Every path is a hard link to one valid EPUB. This measures filesystem enumeration,
Book creation, queueing, and bounded worker memory without consuming 100k copies
of the same bytes. It does not model a varied or NAS-hosted media corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import tempfile
import time
from pathlib import Path

from sqlalchemy import func, select
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
    LibraryReadableResource,
    LibraryResourceAsset,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueLibraryImport,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)

SOURCE = Path(__file__).resolve().parents[4] / "test-data/library/epub/reader-v2.epub"


def _rss_peak_bytes() -> int:
    # macOS reports bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value * 1024 if os.name == "posix" and os.uname().sysname == "Linux" else value


def run(books: int, *, drain: bool) -> None:
    if books < 1:
        raise ValueError("books must be positive")
    with tempfile.TemporaryDirectory(prefix="ermao-book-root-") as directory:
        temporary = Path(directory)
        root = temporary / "books"
        root.mkdir()
        source = temporary / "sample.epub"
        shutil.copy2(SOURCE, source)
        generation_started = time.perf_counter()
        for index in range(books):
            os.link(source, root / f"book-{index:06d}.epub")
        generation_seconds = time.perf_counter() - generation_started
        if shutil.disk_usage(temporary).free < 2 * 1024**3:
            raise RuntimeError("less than 2 GiB free before scanning")

        engine = create_sqlite_engine(temporary / "books.sqlite3")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(
                    Library(
                        id="root-probe",
                        name="Root probe",
                        root_path=str(root),
                        organization_mode="FLAT",
                        min_file_size_bytes=0,
                    )
                )
                db.commit()
                pipeline = build_readable_resource_pipeline(
                    db, Settings(storage_root=str(temporary / "storage"))
                )
                pipeline.continue_import.execute(ContinueLibraryImport("root-probe"))
                worker = build_readable_resource_worker(pipeline)
                scan_started = time.perf_counter()
                scan_outcome = worker.process_once()
                scan_seconds = time.perf_counter() - scan_started
                if scan_outcome != "scan":
                    raise RuntimeError(f"root scan returned {scan_outcome}")
                book_count = db.scalar(select(func.count()).select_from(LibraryBook))
                resource_count = db.scalar(
                    select(func.count()).select_from(LibraryReadableResource)
                )
                ready_after_scan = db.scalar(
                    select(func.count()).select_from(LibraryResourceAsset)
                )
                if (book_count, resource_count) != (books, books):
                    raise AssertionError((book_count, resource_count, books))
                if books >= 200 and not ready_after_scan:
                    raise AssertionError("no Book imported during bounded root discovery")
                print(
                    json.dumps(
                        {
                            "phase": "scan",
                            "books": book_count,
                            "resources": resource_count,
                            "ready_assets": ready_after_scan,
                            "generation_seconds": generation_seconds,
                            "scan_seconds": scan_seconds,
                            "peak_rss_bytes": _rss_peak_bytes(),
                            "database_bytes": (temporary / "books.sqlite3").stat().st_size,
                        }
                    ),
                    flush=True,
                )
                if not drain:
                    return
                import_started = time.perf_counter()
                for attempt in range(books * 3):
                    outcome = worker.process_once()
                    if outcome == "idle":
                        break
                    if attempt % 10000 == 9999:
                        if shutil.disk_usage(temporary).free < 2 * 1024**3:
                            raise RuntimeError("less than 2 GiB free during import")
                        print(
                            json.dumps(
                                {
                                    "phase": "progress",
                                    "worker_calls": attempt + 1,
                                    "elapsed_seconds": time.perf_counter() - import_started,
                                    "peak_rss_bytes": _rss_peak_bytes(),
                                }
                            ),
                            flush=True,
                        )
                else:
                    raise AssertionError("Book import did not reach idle")
                state_counts = dict(
                    db.execute(
                        select(LibraryImportTask.state, func.count())
                        .where(LibraryImportTask.kind == "IMPORT_BOOK")
                        .group_by(LibraryImportTask.state)
                    ).all()
                )
                asset_count = db.scalar(
                    select(func.count()).select_from(LibraryResourceAsset)
                )
                if state_counts != {"SUCCEEDED": books} or asset_count != books:
                    raise AssertionError((state_counts, asset_count, books))
                print(
                    json.dumps(
                        {
                            "phase": "complete",
                            "books": books,
                            "book_task_states": state_counts,
                            "assets": asset_count,
                            "import_seconds": time.perf_counter() - import_started,
                            "peak_rss_bytes": _rss_peak_bytes(),
                            "database_bytes": (temporary / "books.sqlite3").stat().st_size,
                        }
                    ),
                    flush=True,
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", type=int, default=100000)
    parser.add_argument("--drain", action="store_true")
    options = parser.parse_args()
    run(options.books, drain=options.drain)
