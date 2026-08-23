from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.maintenance import (
    DATABASE_MAINTENANCE_RESTORE_VALUE,
    DATABASE_MAINTENANCE_SETTING_KEY,
)
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.models.auth import User
from app.models.library import Library
from app.models.settings import SystemSetting
from tests.support.sqlalchemy import StatementRecorder


def _seed_read_surfaces(engine: Engine) -> None:
    with Session(engine) as db:
        db.add_all(
            [
                Library(
                    id="test-library",
                    name="Test Library",
                    root_path="/test-library",
                    organization_mode="FLAT",
                ),
                User(
                    id="writer-lock-admin",
                    email="writer-lock@example.com",
                    name="Writer lock admin",
                    password_hash=hash_password("starshipnas"),
                    role="admin",
                ),
            ]
        )
        db.commit()
        observed_at = datetime.now(UTC)
        book_node = LibrarySourceNode(
            id="writer-lock-book-node",
            library_id="test-library",
            relative_path="writer-lock/",
            path_key="v1:" + hashlib.sha256(b"writer-lock/").hexdigest(),
            name="writer-lock",
            physical_kind="DIRECTORY",
            observed_size_bytes=None,
            observed_mtime_ns=1,
            observed_at=observed_at,
            updated_at=observed_at,
        )
        resource_node = LibrarySourceNode(
            id="writer-lock-resource-node",
            library_id="test-library",
            relative_path="writer-lock.epub",
            path_key="v1:" + hashlib.sha256(b"writer-lock.epub").hexdigest(),
            name="writer-lock.epub",
            physical_kind="REGULAR_FILE",
            observed_size_bytes=10,
            observed_mtime_ns=1,
            observed_at=observed_at,
            updated_at=observed_at,
        )
        book = LibraryBook(
            library_id="test-library",
            id="writer-lock-book",
            source_node_id=book_node.id,
        )
        book_metadata = LibraryBookMetadata(
            book_id=book.id,
            title="Writer lock reader",
            normalized_title="writer lock reader",
            author="作者",
            normalized_author="作者",
        )
        resource = LibraryReadableResource(
            id="writer-lock-resource",
            library_id="test-library",
            book_id=book.id,
            source_node_id=resource_node.id,
            adapter_id="epub-file",
            adapter_version="1",
            media_kind="EBOOK",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
        resource_metadata = LibraryReadableResourceMetadata(
            resource_id=resource.id,
            title="电子书",
        )
        asset = LibraryResourceAsset(
            id="writer-lock-asset",
            library_id="test-library",
            resource_id=resource.id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
        asset_metadata = LibraryResourceAssetMetadata(
            asset_id=asset.id,
            mime_type="application/epub+zip",
        )
        book.source_node = book_node
        resource.book = book
        resource.source_node = resource_node
        asset.resource = resource
        asset.source_node = resource_node
        db.add_all([book_node, resource_node])
        db.flush()
        db.add(book)
        db.flush()
        db.add(book_metadata)
        db.add(resource)
        db.flush()
        db.add_all([resource_metadata, asset, asset_metadata])
        db.flush()
        db.commit()


def test_get_surfaces_remain_read_only_while_writer_slot_is_held(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    regular_engine = create_sqlite_engine(settings.database_path)
    reader_engine = create_sqlite_engine(settings.database_path, timeout_seconds=0.1)
    bootstrap_database(regular_engine, settings)
    _seed_read_surfaces(regular_engine)
    reader_factory = sessionmaker(
        bind=reader_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=reader_factory)
    blocker = Session(regular_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "writer-lock@example.com",
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
                for path in (
                    "/api/auth/me",
                    "/api/libraries",
                    "/api/books",
                    "/api/reader/v4/resources/writer-lock-resource/bootstrap",
                ):
                    started_at = monotonic()
                    response = client.get(path)
                    elapsed = monotonic() - started_at
                    assert response.status_code == 200, (path, response.text)
                    assert elapsed < 0.75, (path, elapsed)

                assert recorder.dml_count == 0
    finally:
        blocker.rollback()
        blocker.close()
        reader_engine.dispose()
        regular_engine.dispose()


def test_maintenance_state_rejects_new_writes_but_keeps_gets_available(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    _seed_read_surfaces(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={
                "email": "writer-lock@example.com",
                "password": "starshipnas",
            },
        )
        assert login.status_code == 200
        with Session(engine) as maintenance:
            maintenance.add(
                SystemSetting(
                    key=DATABASE_MAINTENANCE_SETTING_KEY,
                    value=DATABASE_MAINTENANCE_RESTORE_VALUE,
                )
            )
            maintenance.commit()

        assert client.get("/api/auth/me").status_code == 200
        response = client.post("/api/auth/session/refresh")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_MAINTENANCE"
    engine.dispose()
