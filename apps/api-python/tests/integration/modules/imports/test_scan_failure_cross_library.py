"""Second-phase acceptance: scan failures stay scoped and never imply success."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)


def _drain(worker: ReadableResourceWorkerProcessor, *, limit: int = 200) -> list[str]:
    outcomes: list[str] = []
    for _ in range(limit):
        outcome = worker.process_once()
        if outcome == "idle":
            break
        outcomes.append(outcome)
    return outcomes


def test_cross_library_move_with_source_and_target_scan_failures(
    tmp_path: Path, caplog
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    roots = {name: tmp_path / name for name in ("lib-a", "lib-b", "lib-c")}
    for root in roots.values():
        root.mkdir()
    try:
        with Session(engine) as db:
            for library_id, root in roots.items():
                db.add(
                    Library(
                        id=library_id,
                        name=library_id,
                        root_path=str(root),
                        organization_mode="FLAT",
                        min_file_size_bytes=0,
                    )
                )
            db.commit()
            pipeline = build_readable_resource_pipeline(db, settings)
            worker = build_readable_resource_worker(pipeline)

            comic = roots["lib-a"] / "Comic"
            comic.mkdir()
            for name in ("1.png", "2.png"):
                Image.new("RGB", (16, 16), "red").save(comic / name)
            (roots["lib-c"] / "c.txt").write_text("readable", encoding="utf-8")
            db.commit()

            for library_id in ("lib-a", "lib-c"):
                pipeline.request_library_scan.execute(
                    RequestLibraryScanCommand(library_id, "WATCHER")
                )
            _drain(worker)
            db.expire_all()
            a_assets = set(
                db.scalars(
                    select(LibraryResourceAsset.id).where(
                        LibraryResourceAsset.library_id == "lib-a"
                    )
                )
            )
            assert len(a_assets) == 2
            assert (
                db.scalar(
                    select(LibraryReadableResource.import_state).where(
                        LibraryReadableResource.library_id == "lib-a"
                    )
                )
                == "READY"
            )

            # Move one member from the source library to the target library.
            moved = roots["lib-b"] / "Moved"
            moved.mkdir()
            (comic / "2.png").rename(moved / "2.png")
            # An unrelated library still has real work to finish.
            (roots["lib-c"] / "c.txt").write_text(
                "readable and changed", encoding="utf-8"
            )
            db.commit()

            original_iter = pipeline.filesystem.iter_directory_entries
            failing_paths = {str(comic), str(roots["lib-b"])}

            def failing(path: Path):
                if str(path) in failing_paths:
                    raise PermissionError("injected enumeration failure")
                yield from original_iter(path)

            with caplog.at_level(
                logging.INFO, logger="ermao.readable_resource_pipeline"
            ):
                failing_pipeline = build_readable_resource_pipeline(db, settings)
                failing_pipeline.filesystem.iter_directory_entries = failing  # type: ignore[method-assign]
                failing_worker = build_readable_resource_worker(failing_pipeline)
                for library_id in ("lib-c", "lib-a", "lib-b"):
                    failing_pipeline.request_library_scan.execute(
                        RequestLibraryScanCommand(library_id, "WATCHER")
                    )
                outcomes = _drain(failing_worker)

            assert "identified" in outcomes
            db.expire_all()
            scans = {
                row.library_id: row
                for row in db.scalars(
                    select(LibraryImportTask).where(
                        LibraryImportTask.kind == "SCAN_LIBRARY"
                    )
                )
            }
            assert scans["lib-a"].state == "FAILED"
            assert scans["lib-a"].error_summary == "SOURCE_SCAN_INCOMPLETE"
            assert scans["lib-b"].state == "FAILED"
            # The unrelated library's changed resource is fully imported.
            c_tasks = db.scalars(
                select(LibraryImportTask).where(
                    LibraryImportTask.library_id == "lib-c",
                    LibraryImportTask.kind == "IMPORT_RESOURCE",
                )
            ).all()
            assert c_tasks and all(task.state == "SUCCEEDED" for task in c_tasks)
            # Incomplete enumeration never prunes the source library.
            a_paths = set(
                db.scalars(
                    select(LibrarySourceNode.relative_path).where(
                        LibrarySourceNode.library_id == "lib-a"
                    )
                )
            )
            assert a_paths == {"Comic", "Comic/1.png", "Comic/2.png"}
            assert (
                set(
                    db.scalars(
                        select(LibraryResourceAsset.id).where(
                            LibraryResourceAsset.library_id == "lib-a"
                        )
                    )
                )
                == a_assets
            )
            # The failed target scan did not falsely complete anything.
            assert (
                db.scalar(
                    select(LibrarySourceNode.id).where(
                        LibrarySourceNode.library_id == "lib-b"
                    )
                )
                is None
            )
            assert not list(
                db.scalars(
                    select(LibraryReadableResource).where(
                        LibraryReadableResource.library_id == "lib-b"
                    )
                )
            )
            assert any(
                "source_tree.scan.directory_unreadable" in record.getMessage()
                and getattr(record, "library_id", None) == "lib-a"
                and "PermissionError" in record.getMessage()
                and "diagnostic_id=diag_" in record.getMessage()
                for record in caplog.records
            )

            # Removing the injected failure recovers both libraries.
            recovered = build_readable_resource_pipeline(db, settings)
            recovered_worker = build_readable_resource_worker(recovered)
            for library_id in ("lib-a", "lib-b"):
                recovered.request_library_scan.execute(
                    RequestLibraryScanCommand(library_id, "WATCHER")
                )
            _drain(recovered_worker)
            db.expire_all()
            a_paths = set(
                db.scalars(
                    select(LibrarySourceNode.relative_path).where(
                        LibrarySourceNode.library_id == "lib-a"
                    )
                )
            )
            assert a_paths == {"Comic", "Comic/1.png"}
            b_paths = set(
                db.scalars(
                    select(LibrarySourceNode.relative_path).where(
                        LibrarySourceNode.library_id == "lib-b"
                    )
                )
            )
            assert b_paths == {"Moved", "Moved/2.png"}
            b_task = db.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.library_id == "lib-b",
                    LibraryImportTask.kind == "IMPORT_RESOURCE",
                )
            )
            assert b_task is not None and b_task.state == "SUCCEEDED"
    finally:
        engine.dispose()
