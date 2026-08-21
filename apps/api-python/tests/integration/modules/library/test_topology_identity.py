"""Database identity invariants for the ADR 0018/0019 topology."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import Library
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()


def _node(
    node_id: str,
    library_id: str,
    relative_path: str,
    physical_kind: str = "REGULAR_FILE",
    *,
    parent_id: str | None = None,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id=library_id,
        parent_id=parent_id,
        parent_physical_kind="DIRECTORY" if parent_id is not None else None,
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=None if physical_kind == "DIRECTORY" else 1,
        observed_mtime_ns=1,
        observed_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
    )


def _bootstrap(tmp_path: Path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    return engine


def _add_library(db: Session, tmp_path: Path, library_id: str) -> None:
    db.add(
        Library(
            id=library_id,
            name=library_id,
            root_path=str(tmp_path / library_id),
            organization_mode="VOLUMES",
        )
    )


def test_source_path_identity_is_unique_per_library_not_globally(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, "library-a")
            _add_library(db, tmp_path, "library-b")
            db.flush()
            db.add(_node("node-a", "library-a", "book/volume.epub"))
            db.add(_node("node-b", "library-b", "book/volume.epub"))
            db.commit()

            db.add(_node("duplicate", "library-a", "book/volume.epub"))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            rows = db.scalars(
                select(LibrarySourceNode).order_by(LibrarySourceNode.library_id)
            ).all()
            assert [(row.library_id, row.relative_path) for row in rows] == [
                ("library-a", "book/volume.epub"),
                ("library-b", "book/volume.epub"),
            ]
    finally:
        engine.dispose()


def test_book_and_resource_anchors_are_unique_source_node_slots(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, "library")
            node = _node("node", "library", "book.epub")
            db.add(node)
            db.flush()
            db.add(
                LibraryBook(
                    id="book-1", library_id="library", source_node_id=node.id
                )
            )
            db.commit()

            db.add(
                LibraryBook(
                    id="book-2", library_id="library", source_node_id=node.id
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            db.add(
                LibraryReadableResource(
                    id="resource-1",
                    library_id="library",
                    book_id="book-1",
                    source_node_id=node.id,
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            db.commit()

            db.add(
                LibraryReadableResource(
                    id="resource-2",
                    library_id="library",
                    book_id="book-1",
                    source_node_id=node.id,
                    adapter_id="epub-file",
                    adapter_version="1",
                    media_kind="EBOOK",
                    format="EPUB",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()


def test_same_source_node_can_be_asset_of_multiple_resources(
    tmp_path: Path,
) -> None:
    engine = _bootstrap(tmp_path)
    try:
        with Session(engine) as db:
            _add_library(db, tmp_path, "library")
            directory = _node("directory", "library", "album", "DIRECTORY")
            track = _node(
                "track",
                "library",
                "album/track.mp3",
                parent_id="directory",
            )
            db.add_all([directory, track])
            db.flush()
            db.add_all(
                [
                    LibraryBook(
                        id="album-book",
                        library_id="library",
                        source_node_id="directory",
                    ),
                    LibraryBook(
                        id="track-book",
                        library_id="library",
                        source_node_id="track",
                    ),
                ]
            )
            db.flush()
            db.add_all(
                [
                    LibraryReadableResource(
                        id="album-resource",
                        library_id="library",
                        book_id="album-book",
                        source_node_id="directory",
                        adapter_id="audio-directory",
                        adapter_version="1",
                        media_kind="AUDIO",
                        format="AUDIOBOOK_DIR",
                    ),
                    LibraryReadableResource(
                        id="track-resource",
                        library_id="library",
                        book_id="track-book",
                        source_node_id="track",
                        adapter_id="audio-file",
                        adapter_version="1",
                        media_kind="AUDIO",
                        format="MP3",
                    ),
                ]
            )
            db.flush()
            db.add_all(
                [
                    LibraryResourceAsset(
                        id="album-track-asset",
                        library_id="library",
                        resource_id="album-resource",
                        source_node_id="track",
                        source_node_physical_kind="REGULAR_FILE",
                        role="TRACK",
                        import_state="READY",
                    ),
                    LibraryResourceAsset(
                        id="track-primary-asset",
                        library_id="library",
                        resource_id="track-resource",
                        source_node_id="track",
                        source_node_physical_kind="REGULAR_FILE",
                        role="PRIMARY",
                        import_state="READY",
                    ),
                ]
            )
            db.commit()

            assets = db.scalars(
                select(LibraryResourceAsset)
                .where(LibraryResourceAsset.source_node_id == "track")
                .order_by(LibraryResourceAsset.resource_id)
            ).all()
            assert [(asset.resource_id, asset.role) for asset in assets] == [
                ("album-resource", "TRACK"),
                ("track-resource", "PRIMARY"),
            ]
    finally:
        engine.dispose()
