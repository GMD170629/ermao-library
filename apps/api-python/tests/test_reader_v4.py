import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import ReaderBookmark, User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.modules.reader.application.navigation_maintenance import (
    RebuildEpubNavigationBatch,
)
from app.modules.reader.infrastructure.epub_navigation_recovery import (
    FileReaderEpubNavigationParser,
)
from app.modules.reader.infrastructure.navigation_maintenance import (
    prepare_epub_navigation_write,
)
from app.modules.reader.infrastructure.uow import (
    SqlAlchemyEpubNavigationMaintenanceUnitOfWork,
)


def _login(client: TestClient, db_session: Session) -> User:
    user = User(
        email="reader-v3@example.com",
        name="Reader V3",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200
    return user


def _ebook_volume(db_session: Session) -> LibraryVolume:
    work = LibraryWork(
        id="work-reader-v3",
        origin="MANUAL",
        title="Reader v4",
        normalized_title="reader v3",
        author="测试作者",
        normalized_author="测试作者",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="media-reader-v3",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id="volume-reader-v3",
        media_version_id=media_version.id,
        title="电子书",
        volume_index=None,
        sort_order=0,
        format="EPUB",
        resource_key="manual:reader-v3",
        import_status="COMPLETED",
    )
    file = LibraryFile(
        id="file-reader-v3",
        volume_id=volume.id,
        path="library/reader-v3.epub",
        fingerprint="sha256:reader-v3",
        hash_status="COMPLETED",
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=10,
        sort_order=0,
    )
    db_session.add_all([work, media_version, volume, file])
    db_session.commit()
    return volume


def _write_reader_epub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<package><metadata><title>Recovered EPUB</title></metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
            <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html><body><nav epub:type="toc">
            <a href="Text/one.xhtml#start">第一章</a>
            <a href="Text/two.xhtml">第二章</a>
            </nav></body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/one.xhtml",
            '<html><body><h1 id="start">第一章</h1></body></html>',
        )
        archive.writestr(
            "OEBPS/Text/two.xhtml", "<html><body><h1>第二章</h1></body></html>"
        )


def test_reader_v4_bootstrap_and_progress_are_volume_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)

    bootstrap_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["schemaVersion"] == 4
    assert bootstrap["progressSnapshot"] is None
    assert bootstrap["volume"]["id"] == volume.id
    assert bootstrap["mediaVersion"] == {
        "id": "media-reader-v3",
        "workId": "work-reader-v3",
        "mediaKind": "EBOOK",
        "completed": False,
    }
    assert "edition" not in bootstrap
    assert bootstrap["sourceFormat"] == "epub"

    progress_response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "web",
            "updatedAtEpochMillis": 1_700_000_001_000,
            "contentFingerprint": bootstrap["contentFingerprint"],
            "location": {
                "kind": "reflow",
                "resourceKey": "chapter-1.xhtml",
                "progression": 0.5,
                "position": 42,
                "textQuote": {"exact": "跨端锚点"},
                "contentFingerprint": {
                    "originalFileHash": "sha256:local-publication",
                    "parserVersion": "readium:3.3.0",
                    "normalizationVersion": "reader-location-v1",
                },
                "engineLocator": {
                    "engine": "readium",
                    "platform": "android",
                    "version": "3.3.0",
                    "payload": {"href": "chapter-1.xhtml"},
                },
            },
            "percent": 50,
        },
    )
    assert progress_response.status_code == 200
    progress = progress_response.json()["data"]["progress"]
    assert set(progress) == {
        "schemaVersion",
        "clientId",
        "updatedAtEpochMillis",
        "percent",
        "location",
        "contentFingerprint",
    }
    assert progress["schemaVersion"] == 4
    assert progress["clientId"] == "web"
    assert progress["updatedAtEpochMillis"] == 1_700_000_001_000
    assert progress["location"]["engineLocator"]["engine"] == "readium"
    assert set(progress["location"]) == {
        "kind",
        "resourceKey",
        "progression",
        "position",
        "textQuote",
        "contentFingerprint",
        "engineLocator",
    }
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.user_id == user.id
    assert stored.volume_id == volume.id
    assert stored.percent == 50
    assert stored.location_json is not None
    initial_bootstrap = client.get(
        f"/api/reader/v4/volumes/{volume.id}/bootstrap"
    ).json()["data"]
    assert initial_bootstrap["progressSnapshot"] == progress

    stale_response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "ios",
            "updatedAtEpochMillis": 1_600_000_000_000,
            "contentFingerprint": "stale-server-token",
            "location": {"kind": "reflow", "progression": 0.1},
            "percent": 10,
        },
    )
    assert stale_response.status_code == 200
    stale_progress = stale_response.json()["data"]["progress"]
    assert stale_progress["clientId"] == "ios"
    assert stale_progress["updatedAtEpochMillis"] == 1_600_000_000_000
    assert stale_progress["percent"] == 10
    assert stale_progress["location"] is None
    assert stale_progress["contentFingerprint"] == bootstrap["contentFingerprint"]
    db_session.expire_all()
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.percent == 10
    assert stored.location_json is None
    assert int(stored.progressed_at.replace(tzinfo=UTC).timestamp() * 1000) == (
        1_600_000_000_000
    )
    assert stored.updated_at != stored.progressed_at
    resumed = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]["progressSnapshot"]
    assert resumed == stale_progress


def test_reader_v4_preserves_non_reflowable_location(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    volume.format = "PDF"
    volume.page_count = 12
    file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    file.kind = "PDF"
    file.mime_type = "application/pdf"
    db_session.commit()
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "ios-pdf",
            "updatedAtEpochMillis": 1_700_000_004_000,
            "percent": 25,
            "location": {"kind": "pdf", "pageNumber": 3},
            "contentFingerprint": bootstrap["contentFingerprint"],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["progress"]["location"] == {
        "kind": "pdf",
        "pageNumber": 3,
        "engineLocator": None,
    }


def test_reader_v4_accepts_position_only_reflow_anchor(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "position-only",
            "updatedAtEpochMillis": 1_700_000_005_000,
            "percent": 20,
            "location": {"kind": "reflow", "position": 1},
            "contentFingerprint": bootstrap["contentFingerprint"],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["progress"]["location"]["position"] == 1


def test_reader_v4_allows_progress_without_location(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "percent-only",
            "updatedAtEpochMillis": 1_700_000_005_001,
            "percent": 20,
            "location": None,
            "contentFingerprint": bootstrap["contentFingerprint"],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["progress"]["location"] is None


@pytest.mark.parametrize(
    "location",
    [
        {"kind": "reflow", "position": 0},
        {
            "kind": "reflow",
            "contentFingerprint": {
                "originalFileHash": "sha256:local",
                "parserVersion": "readium:1",
                "normalizationVersion": "v1",
            },
        },
        {
            "kind": "reflow",
            "progression": 0.5,
            "engineLocator": {
                "engine": "readium",
                "platform": "android",
                "version": "1",
                "payload": {"oversized": "x" * 65_536},
            },
        },
        {
            "kind": "reflow",
            "progression": 0.5,
            "engineLocator": {
                "engine": "unknown",
                "platform": "android",
                "version": "1",
                "payload": {},
            },
        },
        {"type": "pdf", "pageNumber": 1},
        {"kind": "pdf", "pageNumber": 1, "volumeId": "legacy-volume"},
    ],
)
def test_reader_v4_rejects_noncanonical_location_payloads(
    client: TestClient,
    db_session: Session,
    location: dict[str, object],
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "invalid-location",
            "updatedAtEpochMillis": 1_700_000_006_000,
            "percent": 20,
            "location": location,
            "contentFingerprint": bootstrap["contentFingerprint"],
        },
    )

    assert response.status_code == 422
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_rejects_location_kind_that_does_not_match_volume(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "wrong-format",
            "updatedAtEpochMillis": 1_700_000_007_000,
            "percent": 20,
            "location": {"kind": "pdf", "pageNumber": 1},
            "contentFingerprint": bootstrap["contentFingerprint"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "message": "阅读位置格式与卷册格式不匹配",
        "code": "READER_LOCATION_FORMAT_MISMATCH",
        "details": {"expectedKind": "reflow", "receivedKind": "pdf"},
    }
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_rejects_bookmark_kind_that_does_not_match_volume(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/bookmarks",
        json={
            "contentFingerprint": bootstrap["contentFingerprint"],
            "bookmarks": [
                {
                    "id": "wrong-format-bookmark",
                    "location": {"kind": "comic", "pageIndex": 1},
                    "label": "Wrong format",
                    "percent": 20,
                    "createdAt": "2026-08-13T00:00:00Z",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATION_FORMAT_MISMATCH"
    assert db_session.query(ReaderBookmark).count() == 0


def test_volume_reading_status_advances_work_detail_to_next_unfinished_volume(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    first_volume = _ebook_volume(db_session)
    second_volume = LibraryVolume(
        id="volume-reader-v3-2",
        media_version_id=first_volume.media_version_id,
        title="电子书 2",
        volume_index=2,
        sort_order=1,
        format="EPUB",
        resource_key="manual:reader-v3-2",
        import_status="COMPLETED",
    )
    second_file = LibraryFile(
        id="file-reader-v3-2",
        volume_id=second_volume.id,
        path="library/reader-v3-2.epub",
        fingerprint="sha256:reader-v3-2",
        hash_status="COMPLETED",
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=10,
        sort_order=0,
    )
    db_session.add_all([second_volume, second_file])
    db_session.commit()

    finished_response = client.put(
        f"/api/reader/v4/volumes/{first_volume.id}/reading-status",
        json={"status": "FINISHED"},
    )

    assert finished_response.status_code == 200
    assert finished_response.json()["data"] == {
        "volumeId": first_volume.id,
        "status": "FINISHED",
        "percent": 100.0,
    }
    detail = client.get("/api/works/work-reader-v3").json()["data"]["book"]
    assert detail["continueVolumeId"] == second_volume.id
    progresses = db_session.query(LibraryReadingProgress).all()
    assert [
        (progress.user_id, progress.volume_id, progress.percent)
        for progress in progresses
    ] == [(user.id, first_volume.id, 100.0)]
    created_progress = progresses[0]
    assert created_progress.schema_version == 4
    assert created_progress.reader_type == "reflowable"
    assert created_progress.position == "0"
    assert created_progress.page is None
    assert created_progress.extra == "{}"
    assert created_progress.location_type is None
    assert created_progress.location_json is None
    assert created_progress.mutation_id is None
    assert created_progress.client_id == "shuku-library"
    assert created_progress.client_sequence is None
    assert created_progress.source_protocol == "SHUKU_READER_V4"
    assert created_progress.source_device_name is None

    unread_response = client.put(
        f"/api/reader/v4/volumes/{first_volume.id}/reading-status",
        json={"status": "UNREAD"},
    )

    assert unread_response.status_code == 200
    assert unread_response.json()["data"]["percent"] == 0.0
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_volume_reading_status_replaces_all_legacy_progress_state(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)
    legacy_progressed_at = datetime(2025, 1, 1, tzinfo=UTC)
    db_session.add(
        LibraryReadingProgress(
            user_id=user.id,
            volume_id=volume.id,
            reader_type="comic",
            position="legacy-position",
            page=7,
            percent=12,
            extra='{"legacy":true}',
            schema_version=3,
            location_type="comic",
            location_json='{"type":"comic","pageIndex":7}',
            content_fingerprint="sha256:legacy",
            mutation_id="legacy-mutation",
            client_id="legacy-client",
            client_sequence=99,
            progressed_at=legacy_progressed_at,
            source_protocol="SHUKU_WEB",
            source_device_name="Legacy Device",
        )
    )
    db_session.commit()

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/reading-status",
        json={"status": "FINISHED"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    progress = db_session.query(LibraryReadingProgress).one()
    assert progress.schema_version == 4
    assert progress.reader_type == "reflowable"
    assert progress.position == "0"
    assert progress.page is None
    assert progress.percent == 100
    assert progress.extra == "{}"
    assert progress.location_type is None
    assert progress.location_json is None
    assert progress.content_fingerprint != "sha256:legacy"
    assert progress.mutation_id is None
    assert progress.client_id == "shuku-library"
    assert progress.client_sequence is None
    assert progress.progressed_at > legacy_progressed_at
    assert progress.source_protocol == "SHUKU_READER_V4"
    assert progress.source_device_name is None


def test_reader_v4_bootstrap_does_not_parse_or_write_missing_epub_navigation(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    epub = tmp_path / "legacy-without-units.epub"
    _write_reader_epub(epub)
    source_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_file.path = str(epub)
    source_file.size_bytes = epub.stat().st_size
    volume.chapter_count = None
    db_session.commit()

    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    writes: list[str] = []

    def capture_writes(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        context: object,
        _executemany: object,
    ) -> None:
        if (
            getattr(context, "isinsert", False)
            or getattr(context, "isupdate", False)
            or getattr(context, "isdelete", False)
        ):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture_writes)
    try:
        first_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
        second_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    finally:
        event.remove(engine, "before_cursor_execute", capture_writes)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["data"]["units"] == []
    assert second_response.json()["data"]["units"] == []
    assert writes == []
    assert db_session.query(LibraryReadingUnit).count() == 0
    db_session.refresh(volume)
    assert volume.chapter_count is None


def test_reader_navigation_maintenance_repairs_missing_units_outside_get(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume = _ebook_volume(db_session)
    epub = tmp_path / "historical-missing-navigation.epub"
    _write_reader_epub(epub)
    source_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_file.path = str(epub)
    source_file.size_bytes = epub.stat().st_size
    volume.chapter_count = None
    db_session.commit()

    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    maintenance = RebuildEpubNavigationBatch(
        lambda: SqlAlchemyEpubNavigationMaintenanceUnitOfWork(factory),
        FileReaderEpubNavigationParser(tmp_path),
        lambda: datetime(2026, 8, 11, tzinfo=UTC),
        prepare_epub_navigation_write,
    )

    result = maintenance.execute(limit=25)

    assert result.scanned == 1
    assert result.processed == 1
    db_session.expire_all()
    units = (
        db_session.query(LibraryReadingUnit)
        .order_by(LibraryReadingUnit.sort_order)
        .all()
    )
    assert [unit.href for unit in units] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    assert all(
        json.loads(unit.metadata_json)["hrefBase"] == "publication-root"
        for unit in units
    )
    db_session.refresh(volume)
    assert volume.chapter_count == 2
    assert maintenance.execute(limit=25).scanned == 0


def test_reader_navigation_maintenance_cas_skips_changed_source(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume = _ebook_volume(db_session)
    epub = tmp_path / "source-changes-during-parse.epub"
    _write_reader_epub(epub)
    source_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_file.path = str(epub)
    source_file.size_bytes = epub.stat().st_size
    db_session.commit()

    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    delegate = FileReaderEpubNavigationParser(tmp_path)

    class MutatingParser:
        def parse(self, source_path: str):
            chapters = delegate.parse(source_path)
            with factory() as mutation:
                mutation.execute(
                    update(LibraryFile)
                    .where(LibraryFile.id == source_file.id)
                    .values(updated_at=datetime(2026, 8, 12, tzinfo=UTC))
                )
                mutation.commit()
            return chapters

    maintenance = RebuildEpubNavigationBatch(
        lambda: SqlAlchemyEpubNavigationMaintenanceUnitOfWork(factory),
        MutatingParser(),
        lambda: datetime(2026, 8, 11, tzinfo=UTC),
        prepare_epub_navigation_write,
    )

    result = maintenance.execute(limit=25)

    assert result.scanned == 1
    assert result.processed == 0
    db_session.expire_all()
    assert db_session.query(LibraryReadingUnit).count() == 0
    assert db_session.get(LibraryVolume, volume.id).chapter_count is None


def test_reader_v4_bootstrap_returns_legacy_navigation_projection_without_repair(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    epub = tmp_path / "legacy-relative-hrefs.epub"
    _write_reader_epub(epub)
    source_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_file.path = str(epub)
    source_file.size_bytes = epub.stat().st_size
    db_session.add_all(
        [
            LibraryReadingUnit(
                id="legacy-unit-one",
                volume_id=volume.id,
                file_id=source_file.id,
                unit_type="chapter",
                title="第一章",
                href="Text/one.xhtml#start",
                media_type="application/xhtml+xml",
                sort_order=1,
                metadata_json=json.dumps({"idref": "one"}),
            ),
            LibraryReadingUnit(
                id="legacy-unit-two",
                volume_id=volume.id,
                file_id=source_file.id,
                unit_type="chapter",
                title="第二章",
                href="Text/two.xhtml",
                media_type="application/xhtml+xml",
                sort_order=2,
                metadata_json=json.dumps({"idref": "two"}),
            ),
        ]
    )
    volume.chapter_count = 2
    db_session.commit()

    response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")

    assert response.status_code == 200
    assert [unit["href"] for unit in response.json()["data"]["units"]] == [
        "Text/one.xhtml#start",
        "Text/two.xhtml",
    ]
    stored_units = (
        db_session.query(LibraryReadingUnit)
        .order_by(LibraryReadingUnit.sort_order)
        .all()
    )
    assert [unit.id for unit in stored_units] == [
        "legacy-unit-one",
        "legacy-unit-two",
    ]
    assert [unit.href for unit in stored_units] == [
        "Text/one.xhtml#start",
        "Text/two.xhtml",
    ]
    assert all(
        "hrefBase" not in json.loads(unit.metadata_json) for unit in stored_units
    )
    detail_units_response = client.get(
        f"/api/works/work-reader-v3/volumes/{volume.id}/reading-units",
        params={"page": 1, "pageSize": 120},
    )
    assert detail_units_response.status_code == 200


def test_reader_v2_and_edition_file_routes_are_gone(client: TestClient) -> None:
    assert client.get("/api/reader/v2/editions/legacy/bootstrap").status_code == 410
    assert client.get("/api/editions/legacy/file").status_code == 410


def test_reader_v4_bookmarks_fall_back_from_non_iso_created_at(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    fallback_created_at = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)
    db_session.add(
        ReaderBookmark(
            id="reader-v3-legacy-bookmark",
            user_id=user.id,
            volume_id=volume.id,
            content_fingerprint=bootstrap["contentFingerprint"],
            bookmark_id="legacy-created-at",
            location_json=json.dumps(
                {
                    "kind": "reflow",
                    "resourceKey": "chapter-1.xhtml",
                }
            ),
            label="Legacy timestamp",
            percent=10,
            bookmark_created_at="not-an-iso-timestamp",
            created_at=fallback_created_at,
            updated_at=fallback_created_at,
        )
    )
    db_session.commit()

    response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/bookmarks",
        params={"contentFingerprint": bootstrap["contentFingerprint"]},
    )

    assert response.status_code == 200
    bookmark = response.json()["data"]["bookmarks"][0]
    assert bookmark["id"] == "legacy-created-at"
    assert datetime.fromisoformat(bookmark["createdAt"]) == fallback_created_at


def test_volume_file_route_streams_the_selected_volume_only(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    stored_file = test_settings.resolved_storage_root / "library" / "reader-v3.epub"
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"reader-v3")

    response = client.get(f"/api/volumes/{volume.id}/file")

    assert response.status_code == 200
    assert response.content == b"reader-v3"
    assert response.headers["content-type"] == "application/epub+zip"


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("reader-v3.txt", "text/plain"),
        ("reader-v3.pdf", "application/pdf"),
        ("reader-v3.epub", "application/epub+zip"),
        ("reader-v3.cbz", "application/vnd.comicbook+zip"),
        ("reader-v3.mp3", "audio/mpeg"),
    ],
)
def test_volume_file_download_mode_uses_attachment_for_every_media_format(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
    filename: str,
    mime_type: str,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    library_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    library_file.path = f"library/{filename}"
    library_file.mime_type = mime_type
    db_session.commit()
    stored_file = test_settings.resolved_storage_root / library_file.path
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"downloadable")

    inline_response = client.get(f"/api/volumes/{volume.id}/file")
    download_response = client.get(
        f"/api/volumes/{volume.id}/file", params={"download": "true"}
    )

    assert inline_response.status_code == 200
    assert inline_response.headers["content-disposition"].startswith("inline;")
    assert download_response.status_code == 200
    assert download_response.content == b"downloadable"
    assert download_response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{filename}"
    )


def test_work_cover_fallback_uses_media_priority_then_volume_order(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    ebook_volume = _ebook_volume(db_session)
    ebook_volume.cover_path = "covers/ebook.jpg"
    comic_media = LibraryMediaVersion(
        id="media-reader-v3-comic",
        work_id="work-reader-v3",
        media_kind="COMIC",
    )
    comic_volume = LibraryVolume(
        id="volume-reader-v3-comic",
        media_version_id=comic_media.id,
        title="漫画",
        sort_order=-10,
        format="CBZ",
        resource_key="manual:reader-v3-comic",
        cover_path="covers/comic.jpg",
    )
    db_session.add_all([comic_media, comic_volume])
    db_session.commit()
    cover_root = test_settings.resolved_storage_root / "covers"
    cover_root.mkdir(parents=True, exist_ok=True)
    (cover_root / "ebook.jpg").write_bytes(b"ebook-cover")
    (cover_root / "comic.jpg").write_bytes(b"comic-cover")

    response = client.get("/api/works/work-reader-v3/cover")

    assert response.status_code == 200
    assert response.content == b"ebook-cover"


def test_source_and_derived_volumes_keep_independent_progress_and_completion(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    source = _ebook_volume(db_session)
    derived = LibraryVolume(
        id="volume-reader-v3-derived",
        media_version_id=source.media_version_id,
        title="EPUB 副本",
        sort_order=1,
        format="EPUB",
        resource_key="derived:reader-v3",
        derived_from_volume_id=source.id,
        import_status="COMPLETED",
    )
    db_session.add(derived)
    db_session.add(
        LibraryFile(
            id="file-reader-v3-derived",
            volume_id=derived.id,
            path="library/reader-v3-derived.epub",
            fingerprint="sha256:reader-v3-derived",
            hash_status="COMPLETED",
            mtime_ms=2,
            kind="EPUB",
            mime_type="application/epub+zip",
            size_bytes=11,
            sort_order=0,
        )
    )
    db_session.commit()

    source_bootstrap = client.get(
        f"/api/reader/v4/volumes/{source.id}/bootstrap"
    ).json()["data"]
    source_save = client.put(
        f"/api/reader/v4/volumes/{source.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "web",
            "updatedAtEpochMillis": 1_700_000_001_000,
            "contentFingerprint": source_bootstrap["contentFingerprint"],
            "location": {"kind": "reflow", "progression": 1},
            "percent": 100,
        },
    )
    assert source_save.status_code == 200
    assert (
        client.get(f"/api/reader/v4/volumes/{source.id}/bootstrap").json()["data"][
            "mediaVersion"
        ]["completed"]
        is False
    )

    derived_bootstrap = client.get(
        f"/api/reader/v4/volumes/{derived.id}/bootstrap"
    ).json()["data"]
    derived_save = client.put(
        f"/api/reader/v4/volumes/{derived.id}/progress",
        json={
            "schemaVersion": 4,
            "clientId": "web",
            "updatedAtEpochMillis": 1_700_000_002_000,
            "contentFingerprint": derived_bootstrap["contentFingerprint"],
            "location": {"kind": "reflow", "progression": 1},
            "percent": 100,
        },
    )
    assert derived_save.status_code == 200
    assert (
        client.get(f"/api/reader/v4/volumes/{source.id}/bootstrap").json()["data"][
            "mediaVersion"
        ]["completed"]
        is True
    )
    progresses = db_session.query(LibraryReadingProgress).all()
    assert {progress.volume_id for progress in progresses} == {
        source.id,
        derived.id,
    }


def test_reader_v4_openapi_requires_no_edition_or_user_identity(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/reader/v4/volumes/{volume_id}/progress"]["put"]
    request_ref = path["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_name = request_ref.rsplit("/", 1)[-1]
    required = set(schema["components"]["schemas"][request_name]["required"])
    assert required == {
        "schemaVersion",
        "clientId",
        "updatedAtEpochMillis",
        "contentFingerprint",
        "percent",
    }
    components = schema["components"]["schemas"]
    location_schema = components[request_name]["properties"]["location"]["anyOf"][0]
    discriminator = location_schema["discriminator"]
    assert discriminator["propertyName"] == "kind"
    mapping = discriminator["mapping"]
    expected_components = {
        "audio": "AudioLocation",
        "comic": "ComicLocation",
        "pdf": "PdfLocation",
        "reflow": "ReflowLocation",
    }
    assert set(mapping) == set(expected_components)
    location_components: dict[str, dict[str, object]] = {}
    for kind, component_prefix in expected_components.items():
        reference = mapping[kind]
        assert reference.startswith(f"#/components/schemas/{component_prefix}")
        component_name = reference.rsplit("/", 1)[-1]
        location_components[kind] = components[component_name]

    assert set(location_components["reflow"]["properties"]) == {
        "kind",
        "resourceKey",
        "progression",
        "position",
        "textQuote",
        "contentFingerprint",
        "engineLocator",
    }
    assert set(location_components["comic"]["properties"]) == {
        "kind",
        "pageIndex",
        "engineLocator",
    }
    assert set(location_components["pdf"]["properties"]) == {
        "kind",
        "pageNumber",
        "engineLocator",
    }
    assert set(location_components["audio"]["properties"]) == {
        "kind",
        "fileId",
        "chapterId",
        "positionMs",
        "engineLocator",
    }
    reflow_properties = location_components["reflow"]["properties"]
    engine_reference = reflow_properties["engineLocator"]["anyOf"][0]["$ref"]
    assert engine_reference.startswith("#/components/schemas/ReaderEngineLocator")
    engine_component = components[engine_reference.rsplit("/", 1)[-1]]
    assert set(engine_component["required"]) == {
        "engine",
        "platform",
        "version",
        "payload",
    }
    assert "EpubLocation" not in components
    assert "ReflowableLocation" not in components


@pytest.mark.parametrize(
    ("method", "resource"),
    [
        ("get", "bootstrap"),
        ("put", "reading-status"),
        ("put", "progress"),
        ("get", "bookmarks"),
        ("put", "bookmarks"),
    ],
)
def test_reader_v3_volume_routes_are_retired(
    client: TestClient,
    method: str,
    resource: str,
) -> None:
    response = client.request(method, f"/api/reader/v3/volumes/legacy/{resource}")

    assert response.status_code == 410
    assert response.json()["error"]["details"]["replacement"] == (
        f"/api/reader/v4/volumes/{{volumeId}}/{resource}"
    )
