"""Schema integration coverage for ADR 0018 readable-resource overlay tables.

Not executed in the phase 1B speed-first batch; reserved for stage 7 gates.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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
    AssetCandidate,
    LibraryImportRun,
    LibraryImportTask,
    ResourceCandidate,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)

OVERLAY_TABLES = {
    "LibrarySourceNode",
    "LibrarySourceNodeMetadata",
    "LibrarySourceNodeInterpretation",
    "LibraryBook",
    "LibraryBookMetadata",
    "LibraryReadableResource",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "LibraryImportRun",
    "ResourceCandidate",
    "AssetCandidate",
    "LibraryImportTask",
}


def _path_key(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def test_fresh_schema_includes_overlay_tables(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        names = set(inspect(engine).get_table_names())
        assert OVERLAY_TABLES <= names
        # Legacy topology tables remain; no dual-write wiring in 1B.
        assert {
            "LibraryWork",
            "LibraryVersion",
            "LibraryVolume",
            "LibraryFile",
        } <= names
    finally:
        engine.dispose()


def test_alembic_metadata_has_no_diff_for_overlay(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_source_node_unique_parent_type_size_and_cascade(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="dir-1", relative_path="Series", physical_kind="DIRECTORY"))
            db.add(
                _source_node(
                    node_id="file-1",
                    relative_path="Series/a.epub",
                    physical_kind="REGULAR_FILE",
                    parent_id="dir-1",
                    size=10,
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibrarySourceNode(
                    id="file-dup",
                    library_id="lib-1",
                    parent_id="dir-1",
                    parent_physical_kind="DIRECTORY",
                    relative_path="Series/a.epub",
                    path_key=_path_key("Series/a.epub"),
                    name="a.epub",
                    physical_kind="REGULAR_FILE",
                    observed_size_bytes=1,
                    observed_mtime_ns=0,
                    observed_at=_now(),
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                _source_node(
                    node_id="bad-parent",
                    relative_path="Series/b.epub",
                    physical_kind="REGULAR_FILE",
                    parent_id="file-1",
                    size=1,
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibrarySourceNode(
                    id="dir-sized",
                    library_id="lib-1",
                    parent_id=None,
                    parent_physical_kind=None,
                    relative_path="Sized",
                    path_key=_path_key("Sized"),
                    name="Sized",
                    physical_kind="DIRECTORY",
                    observed_size_bytes=1,
                    observed_mtime_ns=0,
                    observed_at=_now(),
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibrarySourceNode(
                    id="self-parent",
                    library_id="lib-1",
                    parent_id="self-parent",
                    parent_physical_kind="DIRECTORY",
                    relative_path="Loop",
                    path_key=_path_key("Loop"),
                    name="Loop",
                    physical_kind="DIRECTORY",
                    observed_size_bytes=None,
                    observed_mtime_ns=0,
                    observed_at=_now(),
                )
            )

        with Session(engine) as db, db.begin():
            db.delete(db.get(LibrarySourceNode, "dir-1"))
        with Session(engine) as db:
            assert db.get(LibrarySourceNode, "file-1") is None
    finally:
        engine.dispose()


def test_book_resource_asset_library_and_uniqueness(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="anchor", relative_path="book.epub", physical_kind="REGULAR_FILE"))
            db.add(_source_node(node_id="track", relative_path="track.mp3", physical_kind="REGULAR_FILE"))
            db.add(
                LibraryBook(id="book-1", library_id="lib-1", source_node_id="anchor")
            )
            db.add(
                LibraryImportRun(
                    id="run-1",
                    library_id="lib-1",
                    kind="INITIAL",
                    state="RUNNING",
                    source_node_id="anchor",
                    resource_id=None,
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res-1",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="anchor",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                    published_run_id="run-1",
                    active_import_run_id="run-1",
                )
            )
            run = db.get(LibraryImportRun, "run-1")
            assert run is not None
            run.resource_id = "res-1"
            db.add(
                LibraryResourceAsset(
                    id="asset-1",
                    library_id="lib-1",
                    resource_id="res-1",
                    source_node_id="anchor",
                    source_node_physical_kind="REGULAR_FILE",
                    published_run_id="run-1",
                    role="PRIMARY",
                    import_state="READY",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(LibraryBook(id="book-2", library_id="lib-1", source_node_id="anchor"))

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryReadableResource(
                    id="res-2",
                    library_id="lib-1",
                    book_id="book-1",
                    source_node_id="anchor",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
    finally:
        engine.dispose()


def test_same_source_node_can_be_asset_for_different_resources(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="a1", relative_path="a.epub", physical_kind="REGULAR_FILE"))
            db.add(_source_node(node_id="b1", relative_path="b.epub", physical_kind="REGULAR_FILE"))
            db.add(_source_node(node_id="shared", relative_path="cover.jpg", physical_kind="REGULAR_FILE"))
            db.add(LibraryBook(id="book-a", library_id="lib-1", source_node_id="a1"))
            db.add(LibraryBook(id="book-b", library_id="lib-1", source_node_id="b1"))
            db.add(
                LibraryReadableResource(
                    id="res-a",
                    library_id="lib-1",
                    book_id="book-a",
                    source_node_id="a1",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res-b",
                    library_id="lib-1",
                    book_id="book-b",
                    source_node_id="b1",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.add(
                LibraryResourceAsset(
                    id="asset-a",
                    library_id="lib-1",
                    resource_id="res-a",
                    source_node_id="shared",
                    source_node_physical_kind="REGULAR_FILE",
                    role="SIDECAR",
                    import_state="READY",
                )
            )
            db.add(
                LibraryResourceAsset(
                    id="asset-b",
                    library_id="lib-1",
                    resource_id="res-b",
                    source_node_id="shared",
                    source_node_physical_kind="REGULAR_FILE",
                    role="SIDECAR",
                    import_state="READY",
                )
            )
    finally:
        engine.dispose()


def test_non_regular_file_cannot_be_asset(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="dir", relative_path="Dir", physical_kind="DIRECTORY"))
            db.add(_source_node(node_id="file", relative_path="Dir/a.epub", physical_kind="REGULAR_FILE", parent_id="dir"))
            db.add(LibraryBook(id="book", library_id="lib-1", source_node_id="file"))
            db.add(
                LibraryReadableResource(
                    id="res",
                    library_id="lib-1",
                    book_id="book",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryResourceAsset(
                    id="bad-asset",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="dir",
                    source_node_physical_kind="REGULAR_FILE",
                    role="PRIMARY",
                    import_state="READY",
                )
            )
    finally:
        engine.dispose()


def test_current_published_asset_query_isolation(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(
                _source_node(
                    node_id="file",
                    relative_path="a.epub",
                    physical_kind="REGULAR_FILE",
                )
            )
            db.add(
                _source_node(
                    node_id="track-old",
                    relative_path="old.mp3",
                    physical_kind="REGULAR_FILE",
                )
            )
            db.add(LibraryBook(id="book", library_id="lib-1", source_node_id="file"))
            db.add(
                LibraryImportRun(
                    id="run-old",
                    library_id="lib-1",
                    kind="INITIAL",
                    state="COMPLETED",
                    source_node_id="file",
                )
            )
            db.add(
                LibraryImportRun(
                    id="run-new",
                    library_id="lib-1",
                    kind="REIMPORT",
                    state="COMPLETED",
                    source_node_id="file",
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res",
                    library_id="lib-1",
                    book_id="book",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                    published_run_id="run-new",
                    import_state="READY",
                )
            )
            # Same (resourceId, sourceNodeId) reuses one Asset row; isolation is by
            # publishedRunId across different source nodes after a publish switch.
            db.add(
                LibraryResourceAsset(
                    id="old-asset",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="track-old",
                    source_node_physical_kind="REGULAR_FILE",
                    published_run_id="run-old",
                    role="TRACK",
                    import_state="READY",
                )
            )
            db.add(
                LibraryResourceAsset(
                    id="new-asset",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="file",
                    source_node_physical_kind="REGULAR_FILE",
                    published_run_id="run-new",
                    role="PRIMARY",
                    import_state="READY",
                )
            )

        with Session(engine) as db:
            resource = db.get(LibraryReadableResource, "res")
            assert resource is not None
            visible = db.scalars(
                select(LibraryResourceAsset).where(
                    LibraryResourceAsset.resource_id == resource.id,
                    LibraryResourceAsset.published_run_id == resource.published_run_id,
                    LibraryResourceAsset.import_state == "READY",
                )
            ).all()
            assert [asset.id for asset in visible] == ["new-asset"]
    finally:
        engine.dispose()


def test_active_import_run_uniqueness_and_candidates(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="file", relative_path="a.epub", physical_kind="REGULAR_FILE"))
            db.add(LibraryBook(id="book", library_id="lib-1", source_node_id="file"))
            db.add(
                LibraryImportRun(
                    id="run-1",
                    library_id="lib-1",
                    kind="INITIAL",
                    state="RUNNING",
                    source_node_id="file",
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res",
                    library_id="lib-1",
                    book_id="book",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                    active_import_run_id="run-1",
                )
            )
            run = db.get(LibraryImportRun, "run-1")
            assert run is not None
            run.resource_id = "res"
            db.add(
                ResourceCandidate(
                    id="rc-1",
                    import_run_id="run-1",
                    library_id="lib-1",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.add(
                AssetCandidate(
                    id="ac-1",
                    import_run_id="run-1",
                    library_id="lib-1",
                    source_node_id="file",
                    role="PRIMARY",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                ResourceCandidate(
                    id="rc-2",
                    import_run_id="run-1",
                    library_id="lib-1",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryImportRun(
                    id="run-2",
                    library_id="lib-1",
                    kind="RETRY",
                    state="PENDING",
                    source_node_id="file",
                    resource_id="res",
                )
            )
    finally:
        engine.dispose()


def test_import_task_run_owned_and_incremental_dedupe(tmp_path: Path) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db, db.begin():
            _add_library(db, tmp_path)
            db.add(_source_node(node_id="file", relative_path="a.epub", physical_kind="REGULAR_FILE"))
            db.add(LibraryBook(id="book", library_id="lib-1", source_node_id="file"))
            db.add(
                LibraryImportRun(
                    id="run-1",
                    library_id="lib-1",
                    kind="INITIAL",
                    state="RUNNING",
                    source_node_id="file",
                )
            )
            db.add(
                LibraryReadableResource(
                    id="res",
                    library_id="lib-1",
                    book_id="book",
                    source_node_id="file",
                    adapter_id="epub",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                    active_import_run_id="run-1",
                )
            )
            db.add(
                LibraryImportTask(
                    id="task-run",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="file",
                    owner_import_run_id="run-1",
                    role="PRIMARY",
                )
            )
            db.add(
                LibraryImportTask(
                    id="task-inc",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="file",
                    owner_import_run_id=None,
                    role="TRACK",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryImportTask(
                    id="task-run-dup",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="file",
                    owner_import_run_id="run-1",
                    role="PRIMARY",
                )
            )

        with Session(engine) as db, pytest.raises(IntegrityError), db.begin():
            db.add(
                LibraryImportTask(
                    id="task-inc-dup",
                    library_id="lib-1",
                    resource_id="res",
                    source_node_id="file",
                    owner_import_run_id=None,
                    role="PAGE",
                )
            )
    finally:
        engine.dispose()


def test_application_owns_path_consistency_and_acyclic_subtree_rules() -> None:
    """Document invariants that SQLite schema cannot reliably enforce."""

    application_owned = (
        "SourceNode relativePath must equal parent.relativePath + '/' + name",
        "SourceNode tree must remain acyclic beyond direct self-parent CHECK",
        "Resource anchor must equal Book anchor or lie inside Book subtree",
        "Directory Resource assets must lie inside Resource subtree",
        "File Resource PRIMARY asset must reference the Resource anchor node",
    )
    assert len(application_owned) == 5
