"""Upgrade a real pre-0018 database and verify legacy failures stay gated."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
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


def _add_legacy_tasks(db: Session, rows: list[LibraryImportTask]) -> None:
    """Write the columns that exist in the database under upgrade."""
    db.flush()
    table = sa.Table("LibraryImportTask", sa.MetaData(), autoload_with=db.get_bind())
    fields = {
        "id": "id",
        "kind": "kind",
        "library_id": "libraryId",
        "resource_id": "resourceId",
        "source_node_id": "sourceNodeId",
        "resource_anchor_node_id": "resourceAnchorNodeId",
        "role": "role",
        "state": "state",
        "scan_scopes": "scanScopes",
        "error_summary": "errorSummary",
        "created_at": "createdAt",
        "finished_at": "finishedAt",
    }
    for row in rows:
        data = {}
        for attribute, column in fields.items():
            value = getattr(row, attribute)
            if value is None or column not in table.c:
                continue
            data[column] = (
                int(value.timestamp() * 1000) if isinstance(value, datetime) else value
            )
        db.execute(table.insert().values(**data))


def _add_legacy_source_node(db: Session, *, node_id: str, library_id: str, path: str) -> None:
    """Insert only columns present before the scan witness migration."""
    db.flush()
    table = sa.Table("LibrarySourceNode", sa.MetaData(), autoload_with=db.get_bind())
    timestamp = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000)
    db.execute(
        table.insert().values(
            id=node_id,
            libraryId=library_id,
            relativePath=path,
            pathKey=SourceNodeRelativePath(path).path_key,
            name=path,
            physicalKind="DIRECTORY",
            observedMtimeNs=0,
            observedAt=timestamp,
            createdAt=timestamp,
            updatedAt=timestamp,
        )
    )


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
            _add_legacy_source_node(
                db, node_id="source-node", library_id="source", path="source"
            )
            _add_legacy_tasks(
                db,
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
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="recovered-success",
                        library_id="recovered",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                        finished_at=datetime(2026, 9, 2, tzinfo=UTC),
                    ),
                ],
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
            assert decode_scan_scopes(
                db.get(LibraryImportScanGap, "source").scopes
            ) == (  # type: ignore[union-attr]
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
            _add_legacy_source_node(
                db, node_id="legacy-node", library_id="legacy", path="book"
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
            _add_legacy_tasks(
                db,
                [
                    LibraryImportTask(
                        id="legacy-scan",
                        library_id="legacy",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        error_summary="SOURCE_SCAN_INCOMPLETE",
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    )
                ],
            )
            _add_legacy_tasks(
                db,
                [
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
                ],
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
            assert (
                db.scalar(
                    select(LibraryReadableResource.import_state).where(
                        LibraryReadableResource.library_id == "legacy"
                    )
                )
                == "READY"
            )
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


def _add_library(db: Session, library_id: str, root: Path) -> None:
    library_root = root / library_id
    library_root.mkdir(parents=True, exist_ok=True)
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


def test_upgrade_from_0018_handles_existing_gap_rows(tmp_path: Path) -> None:
    import json

    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    try:
        _upgrade_to(engine, "0018_library_import_scan_gaps")
        with Session(engine) as db:
            for library_id in ("v-none", "v-null", "v-other"):
                _add_library(db, library_id, root)
            db.add(LibraryImportScanGap(library_id="v-null", scopes=None))
            db.add(
                LibraryImportScanGap(
                    library_id="v-other",
                    scopes=json.dumps([{"relativePath": "keep", "recursive": True}]),
                )
            )
            _add_legacy_tasks(
                db,
                [
                    LibraryImportTask(
                        id="v-none-scan",
                        library_id="v-none",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="v-null-scan",
                        library_id="v-null",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                    LibraryImportTask(
                        id="v-other-scan",
                        library_id="v-other",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        scan_scopes=json.dumps(
                            [{"relativePath": "part", "recursive": False}]
                        ),
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    ),
                ],
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            assert decode_scan_scopes(
                db.get(LibraryImportScanGap, "v-none").scopes
            ) == (  # type: ignore[union-attr]
                ScanScope("", True),
            )
            null_gap = db.get(LibraryImportScanGap, "v-null")
            assert null_gap is not None
            assert decode_scan_scopes(null_gap.scopes) == (ScanScope("", True),)
            assert (
                len(
                    db.scalars(
                        select(LibraryImportScanGap.library_id).where(
                            LibraryImportScanGap.library_id == "v-null"
                        )
                    ).all()
                )
                == 1
            )
            other = decode_scan_scopes(db.get(LibraryImportScanGap, "v-other").scopes)  # type: ignore[union-attr]
            assert other is not None
            assert {scope.relative_path for scope in other} == {"keep", "part"}
    finally:
        engine.dispose()


def test_backfill_uses_execution_time_not_creation_order(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    base = datetime(2026, 9, 1, tzinfo=UTC)
    try:
        _upgrade_to(engine, "0018_library_import_scan_gaps")
        with Session(engine) as db:
            for library_id in ("r1", "r2", "r3", "r4"):
                _add_library(db, library_id, root)
            db.commit()
            # Historical rows are written with the 0018 schema. Their final
            # execution times, not the retained creation times, decide recovery.
            _add_legacy_tasks(
                db,
                [
                    LibraryImportTask(
                        id="r1-failed",
                        library_id="r1",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=base,
                        finished_at=base + timedelta(seconds=200),
                    ),
                    LibraryImportTask(
                        id="r1-success",
                        library_id="r1",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=base + timedelta(seconds=1),
                        finished_at=base + timedelta(seconds=100),
                    ),
                    LibraryImportTask(
                        id="r2-success",
                        library_id="r2",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=base,
                        finished_at=base + timedelta(seconds=200),
                    ),
                    LibraryImportTask(
                        id="r2-failed",
                        library_id="r2",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=base + timedelta(seconds=1),
                        finished_at=base + timedelta(seconds=150),
                    ),
                    LibraryImportTask(
                        id="r3-failed",
                        library_id="r3",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=base,
                    ),
                    LibraryImportTask(
                        id="r3-success",
                        library_id="r3",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=base + timedelta(seconds=1),
                        finished_at=base + timedelta(seconds=200),
                    ),
                    LibraryImportTask(
                        id="r4-failed",
                        library_id="r4",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        created_at=base,
                        finished_at=base + timedelta(seconds=100),
                    ),
                    LibraryImportTask(
                        id="r4-success",
                        library_id="r4",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        created_at=base + timedelta(seconds=1),
                    ),
                ],
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            r1 = db.get(LibraryImportScanGap, "r1")
            assert r1 is not None and r1.scopes
            assert {
                scope.relative_path for scope in decode_scan_scopes(r1.scopes) or ()
            } == {""}
            # r2 recovered by the retried success, so no gap is rebuilt.
            r2 = db.get(LibraryImportScanGap, "r2")
            assert r2 is None or not r2.scopes
            # Unprovable ordering stays gated.
            assert db.get(LibraryImportScanGap, "r3") is not None
            assert db.get(LibraryImportScanGap, "r4") is not None
    finally:
        engine.dispose()


def test_0020_compensates_an_instance_already_at_0019(tmp_path: Path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    try:
        _upgrade_to(engine, "0019_backfill_scan_gaps")
        with Session(engine) as db:
            _add_library(db, "late", root)
            # The already-run 0019 left an empty row and missed the failure.
            db.add(LibraryImportScanGap(library_id="late", scopes=None))
            _add_legacy_tasks(
                db,
                [
                    LibraryImportTask(
                        id="late-scan",
                        library_id="late",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        finished_at=datetime(2026, 9, 1, tzinfo=UTC),
                    )
                ],
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            gap = db.get(LibraryImportScanGap, "late")
            assert gap is not None
            assert decode_scan_scopes(gap.scopes) == (ScanScope("", True),)
            assert (
                len(
                    db.scalars(
                        select(LibraryImportScanGap.library_id).where(
                            LibraryImportScanGap.library_id == "late"
                        )
                    ).all()
                )
                == 1
            )
    finally:
        engine.dispose()


def _add_import_graph(db: Session, library_id: str) -> None:
    node_id = f"{library_id}-node"
    book_id = f"{library_id}-book"
    resource_id = f"{library_id}-resource"
    _add_legacy_source_node(db, node_id=node_id, library_id=library_id, path="book")
    db.add(LibraryBook(id=book_id, library_id=library_id, source_node_id=node_id))
    db.flush()
    db.add(
        LibraryReadableResource(
            id=resource_id,
            library_id=library_id,
            book_id=book_id,
            source_node_id=node_id,
            adapter_id="image_dir",
            adapter_version="1",
            format="IMAGE_DIR",
        )
    )
    db.flush()


def test_backfill_ignores_and_is_not_cleared_by_ordinary_tasks(tmp_path: Path) -> None:
    import json

    settings = Settings(storage_root=str(tmp_path / "storage"))
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    root = tmp_path / "library"
    root.mkdir(parents=True)
    base = datetime(2026, 9, 1, tzinfo=UTC)
    later = base + timedelta(seconds=10)
    local_scope = json.dumps([{"relativePath": "part", "recursive": False}])
    try:
        _upgrade_to(engine, "0018_library_import_scan_gaps")
        with Session(engine) as db:
            for library_id in (
                "import-only",
                "ident-only",
                "asset-only",
                "scan-import",
                "scan-ident",
                "source-import",
                "covered",
            ):
                _add_library(db, library_id, root)
                _add_import_graph(db, library_id)
            _add_legacy_tasks(
                db,
                [
                    # Ordinary failures never create a scan gap.
                    LibraryImportTask(
                        id="t-import",
                        library_id="import-only",
                        kind="IMPORT_RESOURCE",
                        state="FAILED",
                        resource_id="import-only-resource",
                        source_node_id="import-only-node",
                        resource_anchor_node_id="import-only-node",
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-ident",
                        library_id="ident-only",
                        kind="IDENTIFY_BOOK",
                        state="FAILED",
                        source_node_id="ident-only-node",
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-asset",
                        library_id="asset-only",
                        kind="IMPORT_ASSET",
                        state="FAILED",
                        resource_id="asset-only-resource",
                        source_node_id="asset-only-node",
                        role="PRIMARY",
                        finished_at=base,
                    ),
                    # A failed local scan stays gated even if ordinary work
                    # later succeeds; imports are not scan-coverage evidence.
                    LibraryImportTask(
                        id="t-scan-import",
                        library_id="scan-import",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        scan_scopes=local_scope,
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-import-ok",
                        library_id="scan-import",
                        kind="IMPORT_RESOURCE",
                        state="SUCCEEDED",
                        resource_id="scan-import-resource",
                        source_node_id="scan-import-node",
                        resource_anchor_node_id="scan-import-node",
                        finished_at=later,
                    ),
                    LibraryImportTask(
                        id="t-scan-ident",
                        library_id="scan-ident",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        scan_scopes=local_scope,
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-ident-ok",
                        library_id="scan-ident",
                        kind="IDENTIFY_BOOK",
                        state="SUCCEEDED",
                        source_node_id="scan-ident-node",
                        finished_at=later,
                    ),
                    LibraryImportTask(
                        id="t-source",
                        library_id="source-import",
                        kind="CONTINUE_SOURCE",
                        state="FAILED",
                        source_node_id="source-import-node",
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-source-import-ok",
                        library_id="source-import",
                        kind="IMPORT_RESOURCE",
                        state="SUCCEEDED",
                        resource_id="source-import-resource",
                        source_node_id="source-import-node",
                        resource_anchor_node_id="source-import-node",
                        finished_at=later,
                    ),
                    # A real covering scan success does resolve the gap.
                    LibraryImportTask(
                        id="t-scan-covered",
                        library_id="covered",
                        kind="SCAN_LIBRARY",
                        state="FAILED",
                        scan_scopes=local_scope,
                        finished_at=base,
                    ),
                    LibraryImportTask(
                        id="t-scan-ok",
                        library_id="covered",
                        kind="SCAN_LIBRARY",
                        state="SUCCEEDED",
                        finished_at=later,
                    ),
                ],
            )
            db.commit()

        apply_schema(engine, settings)

        with Session(engine) as db:
            assert db.get(LibraryImportScanGap, "import-only") is None
            assert db.get(LibraryImportScanGap, "ident-only") is None
            assert db.get(LibraryImportScanGap, "asset-only") is None
            for library_id in ("scan-import", "scan-ident"):
                gap = db.get(LibraryImportScanGap, library_id)
                assert gap is not None and gap.scopes
                assert {
                    scope.relative_path
                    for scope in decode_scan_scopes(gap.scopes) or ()
                } == {"part"}
            source = db.get(LibraryImportScanGap, "source-import")
            assert source is not None
            assert {
                scope.relative_path for scope in decode_scan_scopes(source.scopes) or ()
            } == {"book"}
            covered = db.get(LibraryImportScanGap, "covered")
            assert covered is None or not covered.scopes
    finally:
        engine.dispose()
