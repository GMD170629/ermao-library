"""Fresh-baseline schema coverage for the ADR 0018/0019 target identity."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)

TARGET_CORE_TABLES = {
    "LibrarySourceNode",
    "LibrarySourceNodeMetadata",
    "LibrarySourceNodeInterpretation",
    "LibraryBook",
    "LibraryBookMetadata",
    "LibraryReadableResource",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "LibraryImportTask",
}

LEGACY_TABLES = {
    "LibraryImportRun",
    "ResourceCandidate",
    "AssetCandidate",
    "LibraryWork",
    "LibraryVersion",
    "LibraryVolume",
    "LibraryFile",
    "LibraryMediaVersion",
    "LibraryReadingUnit",
    "LibraryReadingProgress",
    "LibraryMetadata",
    "LibraryWorkFacet",
    "LibraryVolumeFacet",
    "ShelfWork",
    "WorkDetailPreference",
    "ImportTask",
    "ImportScanJob",
    "ImportWorkItem",
    "ImportAsset",
    "ImportLog",
    "BookIdentityCache",
    "QueueControlOperation",
    "MonitorFolder",
    "UserMonitorFolderAccess",
    "DuplicateCandidate",
    "MediaVersionMigrationEvent",
    "UserMediaHistory",
}


def _path_key(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def _now() -> datetime:
    return datetime.now(UTC)


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(db: Session, tmp_path: Path) -> None:
    db.add(
        Library(
            id="lib-1",
            name="Lib",
            root_path=str(tmp_path / "books"),
            organization_mode="FLAT",
        )
    )


def _source_node(
    *,
    node_id: str,
    relative_path: str,
    physical_kind: str,
    parent_id: str | None = None,
    size: int | None = 1,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="lib-1",
        parent_id=parent_id,
        parent_physical_kind="DIRECTORY" if parent_id is not None else None,
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=size if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=0,
        observed_at=_now(),
    )


def test_fresh_schema_includes_target_tables(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        names = set(inspect(engine).get_table_names())
        assert TARGET_CORE_TABLES <= names
        assert {
            "LibraryBookFacet",
            "LibraryReadableResourceFacet",
            "ShelfBook",
            "BookDetailPreference",
            "ReaderBookPreference",
            "ReaderProgressCursor",
            "ReaderResourceProgress",
            "ReaderProgressMutation",
            "ReaderBookmark",
            "ReadableResourceNavigationUnit",
            "PublicationNavigationCache",
        } <= names
        assert LEGACY_TABLES.isdisjoint(names)
    finally:
        engine.dispose()


def test_alembic_metadata_has_no_diff_for_target_schema(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            diff = compare_metadata(context, Base.metadata)
        target_diff = [
            item
            for item in diff
            if any(table in str(item) for table in TARGET_CORE_TABLES)
        ]
        assert target_diff == []
    finally:
        engine.dispose()


def test_source_node_path_key_unique_and_ready_assets(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.add(
                _source_node(
                    node_id="n1",
                    relative_path="a.epub",
                    physical_kind="REGULAR_FILE",
                )
            )
            db.commit()
            db.add(
                _source_node(
                    node_id="n2",
                    relative_path="a.epub",
                    physical_kind="REGULAR_FILE",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(LibraryBook(id="book-1", library_id="lib-1", source_node_id="n1"))
            db.flush()
            db.add(
                LibraryReadableResource(
                    id="res-1",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="n1",
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.flush()
            db.add(
                LibraryResourceAsset(
                    id="asset-1",
                    library_id="lib-1",
                    resource_id="res-1",
                    source_node_id="n1",
                    role="PRIMARY",
                    import_state="READY",
                )
            )
            db.add(
                LibraryImportTask(
                    id="task-1",
                    kind="IMPORT_ASSET",
                    library_id="lib-1",
                    resource_id="res-1",
                    source_node_id="n1",
                    role="PRIMARY",
                    state="SUCCEEDED",
                )
            )
            db.commit()
            ready = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == "res-1",
                    LibraryResourceAsset.import_state == "READY",
                )
            ).all()
            assert len(ready) == 1
            assert "publishedRunId" not in LibraryReadableResource.__table__.c
            assert "publishedRunId" not in LibraryResourceAsset.__table__.c
            assert "activeImportRunId" not in LibraryReadableResource.__table__.c
            assert "ownerImportRunId" not in LibraryImportTask.__table__.c
            assert {column.name for column in LibraryImportTask.__table__.columns} == {
                "id",
                "kind",
                "libraryId",
                "resourceId",
                "sourceNodeId",
                "role",
                "state",
                "errorSummary",
                "createdAt",
                "startedAt",
                "finishedAt",
            }
    finally:
        engine.dispose()


def test_import_task_kind_shape_and_asset_unique(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path)
            db.add(
                _source_node(
                    node_id="n1",
                    relative_path="a.epub",
                    physical_kind="REGULAR_FILE",
                )
            )
            db.add(LibraryBook(id="book-1", library_id="lib-1", source_node_id="n1"))
            db.flush()
            db.add(
                LibraryReadableResource(
                    id="res-1",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="n1",
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.commit()

            db.add(
                LibraryImportTask(
                    id="scan-1",
                    kind="SCAN_LIBRARY",
                    library_id="lib-1",
                    state="QUEUED",
                )
            )
            db.commit()

            db.add(
                LibraryImportTask(
                    id="bad-scan",
                    kind="SCAN_LIBRARY",
                    library_id="lib-1",
                    source_node_id="n1",
                    state="QUEUED",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(
                LibraryImportTask(
                    id="asset-1",
                    kind="IMPORT_ASSET",
                    library_id="lib-1",
                    resource_id="res-1",
                    source_node_id="n1",
                    role="PRIMARY",
                    state="QUEUED",
                )
            )
            db.commit()

            db.add(
                LibraryImportTask(
                    id="continue-1",
                    kind="CONTINUE_SOURCE",
                    library_id="lib-1",
                    source_node_id="n1",
                    state="QUEUED",
                )
            )
            db.commit()
            db.add(
                LibraryImportTask(
                    id="asset-2",
                    kind="IMPORT_ASSET",
                    library_id="lib-1",
                    resource_id="res-1",
                    source_node_id="n1",
                    role="PRIMARY",
                    state="QUEUED",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()


def test_composite_foreign_keys_reject_cross_library_links(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    Library(
                        id="lib-1",
                        name="Library 1",
                        root_path=str(tmp_path / "lib-1"),
                        organization_mode="FLAT",
                    ),
                    Library(
                        id="lib-2",
                        name="Library 2",
                        root_path=str(tmp_path / "lib-2"),
                        organization_mode="FLAT",
                    ),
                    _source_node(
                        node_id="node-1",
                        relative_path="one.epub",
                        physical_kind="REGULAR_FILE",
                    ),
                    LibrarySourceNode(
                        id="node-2",
                        library_id="lib-2",
                        parent_id=None,
                        parent_physical_kind=None,
                        relative_path="one.epub",
                        path_key=_path_key("one.epub"),
                        name="one.epub",
                        physical_kind="REGULAR_FILE",
                        observed_size_bytes=1,
                        observed_mtime_ns=0,
                        observed_at=_now(),
                    ),
                ]
            )
            db.commit()
            db.add(
                LibraryBook(
                    id="book-1",
                    library_id="lib-1",
                    source_node_id="node-1",
                )
            )
            db.commit()

            db.add(
                LibraryReadableResource(
                    id="cross-library-resource",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="node-2",
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(
                LibraryReadableResource(
                    id="resource-1",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="node-1",
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.commit()
            db.add(
                LibraryResourceAsset(
                    id="cross-library-asset",
                    library_id="lib-1",
                    resource_id="resource-1",
                    source_node_id="node-2",
                    source_node_physical_kind="REGULAR_FILE",
                    role="PRIMARY",
                    import_state="READY",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()
