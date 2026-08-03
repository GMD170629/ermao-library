import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

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
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


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
        title="Reader v3",
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


def test_reader_v3_bootstrap_and_progress_are_volume_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)

    bootstrap_response = client.get(f"/api/reader/v3/volumes/{volume.id}/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["schemaVersion"] == 3
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
        f"/api/reader/v3/volumes/{volume.id}/progress",
        json={
            "schemaVersion": 3,
            "mutationId": "mutation-1",
            "clientId": "web",
            "clientSequence": 1,
            "contentFingerprint": bootstrap["contentFingerprint"],
            "location": {
                "type": "epub",
                "href": "chapter-1.xhtml",
                "progression": 0.5,
            },
            "percent": 50,
        },
    )
    assert progress_response.status_code == 200
    progress = progress_response.json()["data"]["progress"]
    assert progress["volumeId"] == volume.id
    assert "editionId" not in progress
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.user_id == user.id
    assert stored.volume_id == volume.id
    assert stored.percent == 50


def test_reader_v3_bootstrap_recovers_missing_epub_chapters_once(
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

    first_response = client.get(f"/api/reader/v3/volumes/{volume.id}/bootstrap")
    second_response = client.get(f"/api/reader/v3/volumes/{volume.id}/bootstrap")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert [unit["href"] for unit in first_response.json()["data"]["units"]] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    assert db_session.query(LibraryReadingUnit).count() == 2
    db_session.refresh(volume)
    assert volume.chapter_count == 2


def test_reader_v3_bootstrap_repairs_legacy_epub_hrefs_and_preserves_unit_ids(
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

    response = client.get(f"/api/reader/v3/volumes/{volume.id}/bootstrap")

    assert response.status_code == 200
    assert [unit["href"] for unit in response.json()["data"]["units"]] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    repaired_units = (
        db_session.query(LibraryReadingUnit)
        .order_by(LibraryReadingUnit.sort_order)
        .all()
    )
    assert [unit.id for unit in repaired_units] == [
        "legacy-unit-one",
        "legacy-unit-two",
    ]
    assert [unit.href for unit in repaired_units] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    assert all(
        json.loads(unit.metadata_json)["hrefBase"] == "publication-root"
        for unit in repaired_units
    )
    detail_units_response = client.get(
        f"/api/works/work-reader-v3/volumes/{volume.id}/reading-units",
        params={"page": 1, "pageSize": 120},
    )
    assert detail_units_response.status_code == 200


def test_reader_v2_and_edition_file_routes_are_gone(client: TestClient) -> None:
    assert client.get("/api/reader/v2/editions/legacy/bootstrap").status_code == 410
    assert client.get("/api/editions/legacy/file").status_code == 410


def test_reader_v3_bookmarks_fall_back_from_non_iso_created_at(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v3/volumes/{volume.id}/bootstrap").json()[
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
                    "type": "epub",
                    "volumeId": volume.id,
                    "href": "chapter-1.xhtml",
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
        f"/api/reader/v3/volumes/{volume.id}/bookmarks",
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
        title="派生 EPUB",
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
        f"/api/reader/v3/volumes/{source.id}/bootstrap"
    ).json()["data"]
    source_save = client.put(
        f"/api/reader/v3/volumes/{source.id}/progress",
        json={
            "schemaVersion": 3,
            "mutationId": "source-complete",
            "clientId": "web",
            "clientSequence": 1,
            "contentFingerprint": source_bootstrap["contentFingerprint"],
            "location": {"type": "epub", "progression": 1},
            "percent": 100,
        },
    )
    assert source_save.status_code == 200
    assert (
        client.get(f"/api/reader/v3/volumes/{source.id}/bootstrap").json()["data"][
            "mediaVersion"
        ]["completed"]
        is False
    )

    derived_bootstrap = client.get(
        f"/api/reader/v3/volumes/{derived.id}/bootstrap"
    ).json()["data"]
    derived_save = client.put(
        f"/api/reader/v3/volumes/{derived.id}/progress",
        json={
            "schemaVersion": 3,
            "mutationId": "derived-complete",
            "clientId": "web",
            "clientSequence": 2,
            "contentFingerprint": derived_bootstrap["contentFingerprint"],
            "location": {"type": "epub", "progression": 1},
            "percent": 100,
        },
    )
    assert derived_save.status_code == 200
    assert (
        client.get(f"/api/reader/v3/volumes/{source.id}/bootstrap").json()["data"][
            "mediaVersion"
        ]["completed"]
        is True
    )
    progresses = db_session.query(LibraryReadingProgress).all()
    assert {progress.volume_id for progress in progresses} == {
        source.id,
        derived.id,
    }


def test_reader_v3_openapi_requires_no_edition_or_user_identity(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/reader/v3/volumes/{volume_id}/progress"]["put"]
    request_ref = path["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_name = request_ref.rsplit("/", 1)[-1]
    required = set(schema["components"]["schemas"][request_name]["required"])
    assert required == {
        "schemaVersion",
        "mutationId",
        "clientId",
        "clientSequence",
        "contentFingerprint",
        "location",
        "percent",
    }
