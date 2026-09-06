from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.models.settings import SystemEvent
from app.modules.opds.public import (
    OPDS_ENABLED_SETTING_KEY,
    OPDS_PUBLIC_BASE_URL_SETTING_KEY,
)
from app.modules.reader.infrastructure.persistence.models import (
    ReaderResourceProgressV5,
)
from app.modules.system.infrastructure.settings import upsert_setting


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1] or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 100,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _seed_opds_book(db: Session) -> User:
    user = User(
        id="opds-user",
        email="reader@example.com",
        name="Reader",
        password_hash=hash_password("reader-password"),
        role="admin",
    )
    book_node = _node("opds-book-node", "opds-book", directory=True)
    resource_node = _node("opds-resource-node", "books/opds.cbz")
    book = LibraryBook(
        id="opds-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id="opds-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="comic-archive",
        adapter_version="1",
        format="CBZ",
        enablement_state="ENABLED",
        import_state="READY",
    )
    # Keep the canonical Book -> Resource -> Asset graph explicit.  The
    # source-node foreign keys are non-null and SQLAlchemy cannot infer this
    # ordering from the scalar IDs alone.
    db.add_all([user, book_node, resource_node, book])
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book.id,
            title="Escaped & Visible",
            normalized_title="escaped & visible",
            author="Author",
            normalized_author="author",
        )
    )
    db.add(resource)
    db.flush()
    db.add(
        LibraryReadableResourceMetadata(
            resource_id=resource.id,
            title="Resource 1",
            page_count=10,
        )
    )
    db.add(
        LibraryResourceAsset(
            id="opds-asset",
            library_id="test-library",
            resource_id=resource.id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.flush()
    db.commit()
    return user


def _enable_opds(db: Session, public_base_url: str = "http://localhost") -> None:
    upsert_setting(db, OPDS_ENABLED_SETTING_KEY, True)
    upsert_setting(db, OPDS_PUBLIC_BASE_URL_SETTING_KEY, public_base_url)
    db.commit()


def _client(test_settings: Settings, db_session: Session) -> TestClient:
    app = create_app(test_settings, session_factory=lambda: db_session)

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: test_settings
    return TestClient(app)


def test_opds_catalog_keeps_download_and_retires_progression_without_writes(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_book(db_session)
    _enable_opds(db_session)
    dml_statements: list[str] = []

    def capture_dml(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert or context.isupdate or context.isdelete:
            dml_statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture_dml)
    try:
        with _client(test_settings, db_session) as client:
            unauthorized = client.get("/opds/v1.2/catalog")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["www-authenticate"].startswith("Basic ")

            auth = ("reader@example.com", "reader-password")
            catalog = client.get("/opds/v1.2/books", auth=auth)
            assert catalog.status_code == 200
            assert b"Escaped &amp; Visible" in catalog.content
            assert b"/opds/v1.2/books/opds-book" in catalog.content

            search = client.get("/opds/v1.2/search", params={"q": "Visible"}, auth=auth)
            assert search.status_code == 200
            assert b"Escaped &amp; Visible" in search.content

            for feed in (catalog.content, search.content):
                assert b"/opds/v1.2/resources/opds-resource/progression" not in feed
                assert b"application/opds-progression+json" not in feed
                assert b"http://vaemendis.net/opds-pse/stream" not in feed
                assert b"pse:lastRead" not in feed
                assert b"pse:lastReadDate" not in feed

            publication = client.get("/opds/v1.2/books/opds-book", auth=auth)
            assert publication.status_code == 200
            assert b"/opds/v1.2/resources/opds-resource/asset" in publication.content
            assert (
                b"/opds/v1.2/resources/opds-resource/progression"
                not in publication.content
            )
            assert b"application/opds-progression+json" not in publication.content
            assert b"pse:lastRead" not in publication.content
            assert b"pse:lastReadDate" not in publication.content

            progression_url = "/opds/v1.2/resources/opds-resource/progression"
            body = {
                "modified": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "device": {"id": "urn:device:test", "name": "Test Reader"},
                "progression": 0.3,
                "references": ["#page=3"],
            }
            unauthorized_get = client.get(progression_url)
            unauthorized_put = client.put(progression_url, json=body)
            retired_get = client.get(progression_url, auth=auth)
            retired_put = client.put(progression_url, auth=auth, json=body)
            retired_malformed_put = client.put(
                progression_url,
                auth=auth,
                content=b"not-json",
                headers={"Content-Type": "application/opds-progression+json"},
            )

            for response in (unauthorized_get, unauthorized_put):
                assert response.status_code == 401
                assert response.headers["www-authenticate"].startswith("Basic ")
            for response in (retired_get, retired_put, retired_malformed_put):
                assert response.status_code == 410
                assert response.headers["content-type"].startswith(
                    "application/problem+json"
                )
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["vary"] == "Authorization"
                assert response.json() == {
                    "type": "https://shuku.invalid/errors/opds-progression-retired",
                    "title": "OPDS progression is no longer supported.",
                }
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_dml)

    assert dml_statements == []
    progress = db_session.scalar(
        select(ReaderResourceProgress).where(
            ReaderResourceProgress.user_id == "opds-user",
            ReaderResourceProgress.resource_id == "opds-resource",
        )
    )
    assert progress is None
    assert (
        db_session.scalar(
            select(ReaderResourceProgressV5).where(
                ReaderResourceProgressV5.user_id == "opds-user",
                ReaderResourceProgressV5.resource_id == "opds-resource",
            )
        )
        is None
    )


def test_opds_missing_resource_page_does_not_read_or_create_navigation_units(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_book(db_session)
    _enable_opds(db_session)
    dml_statements: list[str] = []

    def capture_dml(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert or context.isupdate or context.isdelete:
            dml_statements.append(statement)

    with _client(test_settings, db_session) as client:
        event.listen(db_session.bind, "before_cursor_execute", capture_dml)
        try:
            response = client.get(
                "/opds/v1.2/resources/opds-resource/pages/0",
                auth=("reader@example.com", "reader-password"),
            )
        finally:
            event.remove(db_session.bind, "before_cursor_execute", capture_dml)

    assert response.status_code == 404
    assert dml_statements == []
    assert (
        db_session.scalar(
            select(func.count()).select_from(ReadableResourceNavigationUnit)
        )
        == 0
    )


def test_opds_authentication_is_read_only_and_does_not_log_credentials(
    test_settings: Settings,
    db_session: Session,
    caplog,
) -> None:
    _seed_opds_book(db_session)
    _enable_opds(db_session)
    caplog.set_level("INFO", logger="app.bootstrap.opds")

    with _client(test_settings, db_session) as client:
        assert client.get("/opds/v1.2/catalog").status_code == 401
        assert (
            client.get(
                "/opds/v1.2/catalog?page=2",
                auth=("reader@example.com", "wrong-password"),
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/opds/v1.2/books",
                auth=("reader@example.com", "reader-password"),
            ).status_code
            == 200
        )

    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0
    assert "reader-password" not in caplog.text


def test_opds_routes_are_absent_when_disabled(
    test_settings: Settings,
    db_session: Session,
) -> None:
    with _client(test_settings, db_session) as client:
        assert client.get("/opds/v1.2/catalog").status_code == 404


def test_system_setting_enables_and_disables_opds_without_restart(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_book(db_session)

    with _client(test_settings, db_session) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "reader@example.com", "password": "reader-password"},
        )
        assert login.status_code == 200
        initial = client.get("/api/system-settings/opds")
        assert initial.status_code == 200
        assert initial.json()["data"]["enabled"] is False

        missing_url = client.put("/api/system-settings/opds", json={"enabled": True})
        assert missing_url.status_code == 409
        assert missing_url.json()["error"]["code"] == "OPDS_PUBLIC_BASE_URL_REQUIRED"

        enabled = client.put(
            "/api/system-settings/opds",
            json={"enabled": True, "publicBaseUrl": "http://reader.example.com"},
        )
        assert enabled.status_code == 200
        assert enabled.json()["data"]["catalogUrl"] == (
            "http://reader.example.com/opds/v1.2/catalog"
        )
        assert (
            client.get(
                "/opds/v1.2/catalog",
                auth=("reader@example.com", "reader-password"),
            ).status_code
            == 200
        )

        disabled = client.put(
            "/api/system-settings/opds",
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert client.get("/opds/v1.2/catalog").status_code == 404
