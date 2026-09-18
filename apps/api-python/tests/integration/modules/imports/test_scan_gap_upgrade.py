"""Upgrade a real pre-0018 database and verify legacy failures stay gated."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import Settings
from app.db.runner import alembic_config_for_engine, apply_schema
from app.db.sqlite import create_sqlite_engine
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportScanGap,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.scan_policy import ScanScope, decode_scan_scopes
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import SourceNodeRelativePath

LEGACY_REVISION = "0017_reset_default_cover_paths"


def _upgrade_to(engine, revision: str) -> None:
    config = alembic_config_for_engine(engine)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def _png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "red").save(path)


def test_legacy_failed_scan_variants_backfill_scopes(tmp_path: Path) -> None:
    import json

    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    try:
        _upgrade_to(engine, LEGACY_REVISION)
        with Session(engine) as db:
            for library_id in ("full", "local", "source", "recovered"):
                library_root = root / library_id
                library_root.mkdir()
                db.add(
                    Library(
                        id=library_id,
                        name=library_id,
                        root_path=str(library_root),
                        organization_mode="FLAT",
                        min_file_size_bytes=0,
                    )
                )
            db.flush()
            db.add(
                LibrarySourceNode(
                    id="source-node",
                    library_id="source",
                    relative_path="source",
                    path_key=SourceNodeRelativePath("source").path_key,
                    name="source",
                    physical_kind="DIRECTORY",
                    observed_size_bytes=None,
                    observed_mtime_ns=0,
                    observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            db.add_all(
                [
                    LibraryImportTask(
                        id="full-scan",
                        library_id="full",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="local-scan",
                        library_id="local",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        scan_scopes=json.dumps(
                            [{"relativePath": "part", "recursive": False}]
                        ),
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="source-scan",
                        library_id="source",
                        kind="CONTINUE_SOURCE",
                        state="FAILED",
                        source_node_id="source-node",
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="recovered-failed",
                        library_id="recovered",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="recovered-success",
                        library_id="recovered",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=datetime(2026, 9, 2, tzinfo=UTC),
                    ),
                ]
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            assert decode_scan_scopes(db.get(LibraryImportScanGap, "full").scopes) == (  # type: ignore[union-attr]
                ScanScope("", True),
            )
            assert decode_scan_scopes(db.get(LibraryImportScanGap, "local").scopes) == (  # type: ignore[union-attr]
                ScanScope("part", False),
            )
            assert decode_scan_scopes(db.get(LibraryImportScanGap, "source").scopes) == (  # type: ignore[union-attr]
                ScanScope("source", True),
            )
            # A later successful full scan already recovered this library.
            assert db.get(LibraryImportScanGap, "recovered") is None
    finally:
        engine.dispose()


def test_legacy_failed_scan_backfilled_and_recovered_without_revival(
    tmp_path: Path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    try:
        _upgrade_to(engine, LEGACY_REVISION)
        with Session(engine) as db:
            db.add(
                Library(
                    id="legacy",
                    name="legacy",
                    root_path=str(root),
                    organization_mode="FLAT",
                    min_file_size_bytes=0,
                )
            )
            db.flush()
            db.add(
                LibrarySourceNode(
                    id="legacy-node",
                    library_id="legacy",
                    relative_path="book",
                    path_key=SourceNodeRelativePath("book").path_key,
                    name="book",
                    physical_kind="DIRECTORY",
                    observed_size_bytes=None,
                    observed_mtime_ns=0,
                    observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            db.add(
                LibraryBook(
                    id="legacy-book",
                    library_id="legacy",
                    source_node_id="legacy-node",
                )
            )
            db.flush()
            db.add(
                LibraryBookMetadata(
                    book_id="legacy-book",
                    title="Legacy",
                    normalized_title="legacy",
                    metadata_pending=False,
                )
            )
            db.flush()
            db.add(
                LibraryReadableResource(
                    id="legacy-resource",
                    library_id="legacy",
                    book_id="legacy-book",
                    source_node_id="legacy-node",
                    adapter_id="image_dir",
                    adapter_version="1",
                    format="IMAGE_DIR",
                )
            )
            db.add(
                LibraryImportTask(
                    id="legacy-scan",
                    library_id="legacy",
                    kind="SCAN_LIBRARY",
                    state="FAILED",
                    error_summary="SOURCE_SCAN_INCOMPLETE",
                    created_at=datetime(2026, 9, 1, tzinfo=UTC),
                    finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            db.add(
                LibraryImportTask(
                    id="legacy-import",
                    library_id="legacy",
                    kind="IMPORT_RESOURCE",
                    state="QUEUED",
                    resource_id="legacy-resource",
                    source_node_id="legacy-node",
                    resource_anchor_node_id="legacy-node",
                    created_at=datetime(2026, 9, 1, tzinfo=UTC),
                )
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            gap = db.get(LibraryImportScanGap, "legacy")
            assert gap is not None and gap.scopes
            assert decode_scan_scopes(gap.scopes) == (ScanScope("", True),)
            pipeline = build_readable_resource_pipeline(db, settings)
            # The unfinished directory is not executable after the upgrade.
            assert pipeline.queue.next_queued() is None

        _png(root / "book" / "1.png")

        with Session(engine) as db:
            pipeline = build_readable_resource_pipeline(db, settings)
            pipeline.request_library_scan.execute(
                RequestLibraryScanCommand("legacy", "WATCHER")
            )
            worker = build_readable_resource_worker(pipeline)
            for _ in range(50):
                if worker.process_once() == "idle":
                    break
            db.expire_all()
            assert (
                db.scalar(
                    select(LibraryImportTask.id).where(
                        LibraryImportTask.library_id == "legacy",
                        LibraryImportTask.kind == "IMPORT_RESOURCE",
                        LibraryImportTask.state == "QUEUED",
                    )
                )
                is None
            )
            assert db.scalar(
                select(LibraryReadableResource.import_state).where(
                    LibraryReadableResource.library_id == "legacy"
                )
            ) == "READY"
            gap = db.get(LibraryImportScanGap, "legacy")
            assert gap is None or not gap.scopes

        # Restarting must not rebuild the recovered gap from the FAILED task.
        with Session(engine) as db:
            worker = build_readable_resource_worker(
                build_readable_resource_pipeline(db, settings)
            )
            assert worker.startup() == 0
            assert worker.process_once() == "idle"
            db.expire_all()
            gap = db.get(LibraryImportScanGap, "legacy")
            assert gap is None or not gap.scopes
            assert (
                db.scalar(
                    select(LibraryImportTask.id).where(
                        LibraryImportTask.library_id == "legacy",
                        LibraryImportTask.kind == "IMPORT_RESOURCE",
                        LibraryImportTask.state == "QUEUED",
                    )
                )
                is None
            )
    finally:
        engine.dispose()
