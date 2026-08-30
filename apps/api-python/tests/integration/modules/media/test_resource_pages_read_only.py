from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.auth import User
from app.models.library import Library, ReadableResourceNavigationUnit
from app.models.settings import SystemSetting
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from tests.support.sqlalchemy import StatementRecorder


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _node(
    node_id: str,
    relative_path: str,
    *,
    physical_kind: str,
    size_bytes: int | None,
    mtime_ms: int = 1,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=Path(relative_path).name or node_id,
        physical_kind=physical_kind,
        observed_size_bytes=size_bytes if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=mtime_ms * 1_000_000,
        observed_at=datetime.now(UTC),
    )


def _write_comic_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("001.jpg", b"one")
        archive.writestr("002.jpg", b"two")


def _seed_comic(engine: Engine, settings: Settings) -> tuple[datetime, str]:
    archive_path = settings.resolved_storage_root / "library" / "comic.cbz"
    _write_comic_archive(archive_path)
    preserved_updated_at = datetime(2026, 8, 11, 8, tzinfo=UTC)
    book_id = "comic-lock-book"
    resource_id = "comic-lock-resource"
    asset_id = "comic-lock-asset"
    archive_relative_path = "library/comic.cbz"
    with Session(engine) as db:
        db.add(
            Library(
                id="test-library",
                name="Test Library",
                root_path=str(settings.resolved_storage_root),
                organization_mode="FLAT",
            )
        )
        user = User(
            id="comic-lock-admin",
            email="comic-lock@example.com",
            name="Comic lock admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
        book_node = _node(
            "comic-lock-book-node",
            "comic-lock-book/",
            physical_kind="DIRECTORY",
            size_bytes=None,
        )
        source_node = _node(
            "comic-lock-source-node",
            archive_relative_path,
            physical_kind="REGULAR_FILE",
            size_bytes=archive_path.stat().st_size,
            mtime_ms=int(archive_path.stat().st_mtime * 1000),
        )
        book = LibraryBook(
            id=book_id,
            library_id="test-library",
            source_node_id=book_node.id,
        )
        book_metadata = LibraryBookMetadata(
            book_id=book_id,
            title="Comic lock",
            normalized_title="comic lock",
            author="作者",
            normalized_author="作者",
        )
        resource = LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=source_node.id,
            adapter_id="comic",
            adapter_version="1",
            format="CBZ",
            enablement_state="ENABLED",
            import_state="READY",
        )
        resource_metadata = LibraryReadableResourceMetadata(
            resource_id=resource_id,
            title="Comic lock",
            updated_at=preserved_updated_at,
        )
        asset = LibraryResourceAsset(
            id=asset_id,
            library_id="test-library",
            resource_id=resource_id,
            source_node_id=source_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
            sequence_index=0,
            sort_key="0",
        )
        asset_metadata = LibraryResourceAssetMetadata(
            asset_id=asset_id,
            mime_type="application/vnd.comicbook+zip",
        )
        book.source_node = book_node
        resource.book = book
        resource.source_node = source_node
        asset.resource = resource
        asset.source_node = source_node
        db.add_all([user, book_node, source_node])
        db.flush()
        db.add(book)
        db.flush()
        db.add_all([book_metadata, resource])
        db.flush()
        db.add_all([resource_metadata, asset])
        db.flush()
        db.add(asset_metadata)
        db.commit()
    return preserved_updated_at, resource_id


def test_missing_comic_page_index_does_not_fallback_while_writer_is_held(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    writer_engine = create_sqlite_engine(settings.database_path)
    reader_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.1)
    bootstrap_database(writer_engine, settings)
    preserved_updated_at, resource_id = _seed_comic(writer_engine, settings)
    reader_factory = sessionmaker(
        bind=reader_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=reader_factory)
    blocker = Session(writer_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "comic-lock@example.com",
                    "password": "starshipnas",
                },
            )
            assert login.status_code == 200
            blocker.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "systemName")
                .values(value="writer owns SQLite slot")
            )

            with StatementRecorder(reader_engine) as recorder:
                recorder.reset_after_warmup()
                started_at = monotonic()
                listed = client.get(f"/api/resources/{resource_id}/pages")
                list_elapsed = monotonic() - started_at
                revision = listed.json()["data"]["revision"]
                started_at = monotonic()
                page = client.get(
                    f"/api/resources/{resource_id}/pages/2",
                    params={"revision": revision},
                )
                page_elapsed = monotonic() - started_at

            assert listed.status_code == 200
            assert listed.json()["data"]["pages"] == []
            assert revision.startswith("sha256:")
            assert page.status_code == 404
            assert list_elapsed < 0.75
            assert page_elapsed < 0.75
            assert recorder.dml_count == 0

            with Session(reader_engine) as verification:
                page_rows = verification.scalar(
                    select(func.count()).select_from(ReadableResourceNavigationUnit)
                )
                resource_state = verification.execute(
                    select(
                        LibraryReadableResourceMetadata.updated_at,
                    ).where(LibraryReadableResourceMetadata.resource_id == resource_id)
                ).one()
            assert page_rows == 0
            assert resource_state == (preserved_updated_at,)
    finally:
        blocker.rollback()
        blocker.close()
        reader_engine.dispose()
        writer_engine.dispose()
