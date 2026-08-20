from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import SystemEvent
from app.modules.opds.public import (
    OPDS_ENABLED_SETTING_KEY,
    OPDS_PUBLIC_BASE_URL_SETTING_KEY,
)
from app.modules.system.infrastructure.settings import upsert_setting


def _seed_opds_publication(db: Session) -> User:
    user = User(
        id="opds-user",
        email="reader@example.com",
        name="Reader",
        password_hash=hash_password("reader-password"),
        role="admin",
    )
    work = LibraryWork(
            library_id="test-library", 
        id="opds-work",
        title="Escaped & Visible",
        normalized_title="escaped & visible",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    media = LibraryMediaVersion(
        id="opds-media",
        work_id=work.id,
        media_kind="COMIC",
    )
    volume = LibraryVolume(
        id="opds-volume",
        version_id=media.id,
        title="Volume 1",
        format="CBZ",
        resource_key="opds:volume",
        import_status="COMPLETED",
        page_count=10,
    )
    db.add_all(
        [
            user,
            work,
            media,
            volume,
            LibraryFile(
                id="opds-file",
                volume_id=volume.id,
                path="books/opds.cbz",
                kind="BOOK",
                mime_type="application/vnd.comicbook+zip",
                size_bytes=100,
            ),
        ]
    )
    db.commit()
    return user


def _enable_opds(db: Session, public_base_url: str = "http://localhost") -> None:
    upsert_setting(db, OPDS_ENABLED_SETTING_KEY, True)
    upsert_setting(db, OPDS_PUBLIC_BASE_URL_SETTING_KEY, public_base_url)
    db.commit()


def test_opds_basic_catalog_and_progression_contract(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_publication(db_session)
    _enable_opds(db_session)
    settings = test_settings
    app = create_app(settings, session_factory=lambda: db_session)

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        unauthorized = client.get("/opds/v1.2/catalog")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["www-authenticate"].startswith("Basic ")
        assert "/opds/authentication.json" in unauthorized.headers["link"]
        assert "set-cookie" not in unauthorized.headers

        auth = ("reader@example.com", "reader-password")
        catalog = client.get("/opds/v1.2/works", auth=auth)
        assert catalog.status_code == 200
        assert catalog.headers["vary"] == "Authorization"
        assert "application/atom+xml" in catalog.headers["content-type"]
        assert b"Escaped &amp; Visible" in catalog.content

        search_description = client.get("/opds/v1.2/opensearch.xml", auth=auth)
        assert search_description.status_code == 200
        assert "opensearchdescription+xml" in search_description.headers["content-type"]
        assert b"q={searchTerms}&amp;page=1" in search_description.content

        publication = client.get("/opds/v1.2/works/opds-work", auth=auth)
        assert publication.status_code == 200
        assert b'pse:count="10"' in publication.content
        assert b"/pages/{pageNumber}" in publication.content

        modified = datetime.now(UTC).replace(microsecond=0)
        body = {
            "modified": modified.isoformat(),
            "device": {"id": "urn:device:test", "name": "Test Reader"},
            "progression": 0.3,
            "references": ["#page=3"],
        }
        saved = client.put(
            "/opds/v1.2/volumes/opds-volume/progression", auth=auth, json=body
        )
        assert saved.status_code == 201
        progress = db_session.scalar(
            select(LibraryReadingProgress).where(
                LibraryReadingProgress.user_id == "opds-user",
                LibraryReadingProgress.volume_id == "opds-volume",
            )
        )
        assert progress is not None
        assert progress.schema_version == 3
        assert progress.mutation_id is not None
        assert progress.mutation_id.startswith("opds-")
        assert progress.client_id == "urn:device:test"
        assert progress.client_sequence == int(modified.timestamp() * 1000)
        assert progress.source_protocol == "OPDS_PROGRESSION_1"
        assert progress.source_device_name == "Test Reader"

        stale_body = {**body, "modified": (modified - timedelta(seconds=1)).isoformat()}
        stale = client.put(
            "/opds/v1.2/volumes/opds-volume/progression",
            auth=auth,
            json=stale_body,
        )
        assert stale.status_code == 409
        assert stale.json()["type"].endswith("progression-date")


def test_opds_missing_comic_page_index_does_not_read_archive(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_publication(db_session)
    _enable_opds(db_session)
    archive_path = test_settings.resolved_storage_root / "books" / "opds.cbz"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    page_image = BytesIO()
    Image.new("RGB", (16, 24), color=(120, 40, 20)).save(page_image, format="PNG")
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("001.png", page_image.getvalue())
    source = db_session.get(LibraryFile, "opds-file")
    assert source is not None
    source.path = str(archive_path.relative_to(test_settings.resolved_storage_root))
    source.kind = "COMIC"
    source.size_bytes = archive_path.stat().st_size
    db_session.commit()
    app = create_app(test_settings, session_factory=lambda: db_session)
    dml_statements: list[str] = []

    def capture_dml(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert or context.isupdate or context.isdelete:
            dml_statements.append(statement)

    with TestClient(app) as client:
        event.listen(db_session.bind, "before_cursor_execute", capture_dml)
        try:
            response = client.get(
                "/opds/v1.2/volumes/opds-volume/pages/0",
                auth=("reader@example.com", "reader-password"),
            )
        finally:
            event.remove(db_session.bind, "before_cursor_execute", capture_dml)

    assert response.status_code == 404
    assert dml_statements == []
    assert db_session.scalar(select(func.count()).select_from(LibraryReadingUnit)) == 0


def test_opds_basic_login_requests_are_logged_without_database_writes(
    test_settings: Settings,
    db_session: Session,
    caplog,
) -> None:
    _seed_opds_publication(db_session)
    _enable_opds(db_session)
    caplog.set_level("INFO", logger="app.bootstrap.opds")
    app = create_app(test_settings, session_factory=lambda: db_session)

    dml_statements: list[str] = []

    def capture_dml(conn, cursor, statement, parameters, context, executemany):
        if context.isinsert or context.isupdate or context.isdelete:
            dml_statements.append(statement)

    with TestClient(app) as client:
        event.listen(db_session.bind, "before_cursor_execute", capture_dml)
        try:
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
                    "/opds/v1.2/works",
                    auth=("reader@example.com", "reader-password"),
                ).status_code
                == 200
            )
        finally:
            event.remove(db_session.bind, "before_cursor_execute", capture_dml)

    assert dml_statements == []
    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0
    assert "opds.authentication outcome=failed" in caplog.text
    assert "opds.authentication outcome=succeeded" in caplog.text
    assert "reader-password" not in caplog.text


def test_opds_throttled_login_request_is_logged_without_database_write(
    test_settings: Settings,
    db_session: Session,
    caplog,
) -> None:
    _seed_opds_publication(db_session)
    _enable_opds(db_session)
    upsert_setting(db_session, "language", "en-US")
    db_session.commit()
    app = create_app(test_settings, session_factory=lambda: db_session)

    with TestClient(app) as client:
        for _ in range(5):
            assert (
                client.get(
                    "/opds/v1.2/catalog",
                    auth=("reader@example.com", "wrong-password"),
                ).status_code
                == 401
            )
        throttled = client.get(
            "/opds/v1.2/catalog",
            auth=("reader@example.com", "wrong-password"),
        )
        assert throttled.status_code == 429

    assert db_session.scalar(select(func.count()).select_from(SystemEvent)) == 0
    assert caplog.text.count("opds.authentication outcome=failed") == 5
    assert "opds.authentication outcome=throttled" in caplog.text
    assert "reader-password" not in caplog.text


def test_opds_routes_are_absent_when_disabled(
    test_settings: Settings,
    db_session: Session,
) -> None:
    with TestClient(
        create_app(test_settings, session_factory=lambda: db_session)
    ) as client:
        assert client.get("/opds/v1.2/catalog").status_code == 404


def test_system_setting_enables_and_disables_opds_without_restart(
    test_settings: Settings,
    db_session: Session,
) -> None:
    _seed_opds_publication(db_session)
    settings = test_settings
    app = create_app(settings, session_factory=lambda: db_session)

    def session_override():
        yield db_session

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "reader@example.com", "password": "reader-password"},
        )
        assert login.status_code == 200

        initial = client.get("/api/system-settings/opds")
        assert initial.status_code == 200
        assert initial.json()["data"] == {
            "enabled": False,
            "configured": False,
            "publicBaseUrl": None,
            "catalogUrl": None,
        }

        missing_url = client.put("/api/system-settings/opds", json={"enabled": True})
        assert missing_url.status_code == 409
        assert missing_url.json()["error"]["code"] == "OPDS_PUBLIC_BASE_URL_REQUIRED"

        unsafe_url = client.put(
            "/api/system-settings/opds",
            json={
                "enabled": True,
                "publicBaseUrl": "https://user:password@reader.example.com",
            },
        )
        assert unsafe_url.status_code == 400
        assert unsafe_url.json()["error"]["code"] == "OPDS_PUBLIC_BASE_URL_INVALID"

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

        changed = client.put(
            "/api/system-settings/opds",
            json={"enabled": True, "publicBaseUrl": "https://reader.example.com"},
        )
        assert changed.status_code == 200
        feed = client.get(
            "/opds/v1.2/catalog",
            auth=("reader@example.com", "reader-password"),
        )
        assert b"https://reader.example.com/opds/v1.2/works" in feed.content

        disabled = client.put(
            "/api/system-settings/opds",
            json={
                "enabled": False,
                "publicBaseUrl": "https://reader.example.com",
            },
        )
        assert disabled.status_code == 200
        assert (
            client.get(
                "/opds/v1.2/catalog",
                auth=("reader@example.com", "reader-password"),
            ).status_code
            == 404
        )
