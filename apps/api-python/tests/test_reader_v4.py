import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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
    source_path = (
        Path(__file__).parents[3] / "test-data" / "library" / "epub" / "reader-v2.epub"
    )
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
        path=str(source_path),
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=source_path.stat().st_size,
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
            "<container><rootfiles>"
            '<rootfile full-path="OEBPS/content.opf"/>'
            "</rootfiles></container>",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<package><metadata><title>Recovered EPUB</title></metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
            properties="nav"/>
            <item id="one" href="Text/one.xhtml" media-type="application/xhtml+xml"/>
            <item id="two" href="Text/two.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="one"/>
            <itemref idref="two"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
            xmlns:epub="http://www.idpf.org/2007/ops"><head>
            <title>目录</title></head><body><nav epub:type="toc"><ol>
            <li><a href="Text/one.xhtml#start">第一章</a></li>
            <li><a href="Text/two.xhtml">第二章</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/one.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
            <title>第一章</title></head><body><h1 id="start">第一章</h1>
            </body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/two.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
            <title>第二章</title></head><body><h1>第二章</h1></body></html>""",
        )


def _exact_locator(
    bootstrap: dict[str, object],
    *,
    href: str = "OEBPS/chapter1.xhtml",
    media_type: str = "application/xhtml+xml",
    progression: float = 0.5,
    total_progression: float | None = 0.5,
    platform: str = "web",
) -> dict[str, object]:
    locations: dict[str, object] = {
        "cssSelector": "#paragraph-42",
        "progression": progression,
        "position": 42,
    }
    if total_progression is not None:
        locations["totalProgression"] = total_progression
    return {
        "kind": "reflowable",
        "engineLocator": {
            "engine": "readium",
            "platform": platform,
            "version": "readium-test:1",
            "payload": {
                "href": href,
                "type": media_type,
                "locations": locations,
                "text": {
                    "before": "前文",
                    "highlight": "跨端锚点",
                    "after": "后文",
                },
            },
        },
    }


def _exact_pdf_locator(
    bootstrap: dict[str, object], *, page_index: int, page_progression: float
) -> dict[str, object]:
    return {
        "kind": "pdf",
        "pageIndex": page_index,
        "pageProgression": page_progression,
    }


def _exact_comic_locator(
    bootstrap: dict[str, object], *, page_index: int, resource_href: str
) -> dict[str, object]:
    return {
        "kind": "comic",
        "pageIndex": page_index,
        "resourceHref": resource_href,
    }


def _exact_audio_locator(
    bootstrap: dict[str, object],
    *,
    file_id: str,
    chapter_id: str | None,
    position_millis: int,
) -> dict[str, object]:
    locator: dict[str, object] = {
        "kind": "audio",
        "fileId": file_id,
        "positionMillis": position_millis,
    }
    if chapter_id is not None:
        locator["chapterId"] = chapter_id
    return locator


def _progress_payload(
    bootstrap: dict[str, object],
    *,
    base_revision: int = 0,
    mutation_id: str | None = None,
    locator: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": 4,
        "clientId": "web-installation",
        "mutationId": mutation_id or str(uuid4()),
        "baseRevision": base_revision,
        "capturedAtEpochMillis": 1_700_000_001_000,
        "locator": locator or _exact_locator(bootstrap),
    }


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
    empty_progress_response = client.get(f"/api/reader/v4/volumes/{volume.id}/progress")
    assert empty_progress_response.status_code == 200
    assert empty_progress_response.headers["etag"] == '"reader-progress-0"'
    assert empty_progress_response.json()["data"] == {
        "schemaVersion": 4,
        "progressSnapshot": None,
    }
    assert bootstrap["volume"]["id"] == volume.id
    assert bootstrap["mediaVersion"] == {
        "id": "media-reader-v3",
        "workId": "work-reader-v3",
        "mediaKind": "EBOOK",
        "completed": False,
    }
    assert "edition" not in bootstrap
    assert bootstrap["sourceFormat"] == "epub"
    assert "publicationFingerprint" not in bootstrap
    assert "contentFingerprint" not in bootstrap
    assert all("contentHash" not in file for file in bootstrap["files"])

    mutation_id = str(uuid4())
    progress_response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, mutation_id=mutation_id),
    )
    assert progress_response.status_code == 200
    progress = progress_response.json()["data"]
    assert set(progress) == {
        "schemaVersion",
        "clientId",
        "revision",
        "locator",
        "displayPercent",
        "receivedAtEpochMillis",
        "capturedAtEpochMillis",
    }
    assert progress["schemaVersion"] == 4
    assert progress["clientId"] == "web-installation"
    assert progress["revision"] == 1
    assert progress["displayPercent"] == 50
    assert progress["capturedAtEpochMillis"] == 1_700_000_001_000
    assert progress["locator"]["kind"] == "reflowable"
    assert progress["locator"]["engineLocator"]["engine"] == "readium"
    assert progress["locator"]["engineLocator"]["payload"]["href"] == (
        "OEBPS/chapter1.xhtml"
    )
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.user_id == user.id
    assert stored.volume_id == volume.id
    assert stored.percent == 50
    assert stored.location_json is not None
    assert stored.revision == 1
    assert stored.mutation_id == mutation_id
    initial_bootstrap = client.get(
        f"/api/reader/v4/volumes/{volume.id}/bootstrap"
    ).json()["data"]
    assert initial_bootstrap["progressSnapshot"] == progress

    progress_query = client.get(f"/api/reader/v4/volumes/{volume.id}/progress")
    assert progress_query.status_code == 200
    assert progress_query.headers["etag"] == '"reader-progress-1"'
    assert progress_query.json()["data"] == {
        "schemaVersion": 4,
        "progressSnapshot": progress,
    }
    unchanged = client.get(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        headers={"If-None-Match": progress_query.headers["etag"]},
    )
    assert unchanged.status_code == 304
    assert unchanged.content == b""

    stale_response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            base_revision=0,
            locator=_exact_locator(
                bootstrap, progression=0.1, total_progression=0.1, platform="ios"
            ),
        ),
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "READER_PROGRESS_CONFLICT"
    assert stale_response.json()["error"]["current"] == progress
    db_session.expire_all()
    stored = db_session.query(LibraryReadingProgress).one()
    assert stored.percent == 50
    assert stored.revision == 1
    resumed = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]["progressSnapshot"]
    assert resumed == progress

    repeated = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            base_revision=0,
            mutation_id=mutation_id,
        ),
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"] == progress


def test_reader_v4_first_exact_save_replaces_status_only_revision_zero_row(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    finished = client.put(
        f"/api/reader/v4/volumes/{volume.id}/reading-status",
        json={"status": "FINISHED"},
    )
    assert finished.status_code == 200
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    saved = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, base_revision=0),
    )

    assert saved.status_code == 200, saved.json()
    assert saved.json()["data"]["revision"] == 1
    progress = db_session.query(LibraryReadingProgress).one()
    assert progress.location_type == "reflowable"
    assert progress.revision == 1


def test_reader_v4_validates_pdf_progress_against_canonical_page_index(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    volume.format = "PDF"
    volume.page_count = 12
    file.kind = "PDF"
    file.mime_type = "application/pdf"
    db_session.commit()
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    assert bootstrap["sourceFormat"] == "pdf"

    nullable_locator = _exact_pdf_locator(
        bootstrap, page_index=2, page_progression=0.25
    )
    nullable_locator["engineLocator"] = None
    explicit_null = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, locator=nullable_locator),
    )
    assert explicit_null.status_code == 422

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            locator=_exact_pdf_locator(bootstrap, page_index=2, page_progression=0.25),
        ),
    )

    assert response.status_code == 200
    assert "engineLocator" not in response.json()["data"]["locator"]

    out_of_range = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            base_revision=1,
            locator=_exact_pdf_locator(bootstrap, page_index=12, page_progression=0.25),
        ),
    )
    assert out_of_range.status_code == 422
    error_code = out_of_range.json()["error"]["code"]
    assert error_code == "READER_LOCATOR_RESOURCE_INVALID"


def test_reader_v4_validates_comic_progress_against_indexed_page_media_type(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    volume.format = "CBZ"
    volume.page_count = 2
    file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    file.kind = "CBZ"
    file.mime_type = "application/vnd.comicbook+zip"
    db_session.add_all(
        [
            LibraryReadingUnit(
                id=f"comic-page-{page_number}",
                volume_id=volume.id,
                file_id=file.id,
                unit_type="page",
                title=f"Page {page_number}",
                href=f"images/{page_number:04}.jpg",
                media_type="image/jpeg",
                sort_order=page_number,
                metadata_json="{}",
            )
            for page_number in (1, 2)
        ]
    )
    db_session.commit()
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    assert bootstrap["sourceFormat"] == "cbz"

    accepted = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            locator=_exact_comic_locator(
                bootstrap, page_index=1, resource_href="images/0002.jpg"
            ),
        ),
    )
    wrong_media_type = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            locator=_exact_comic_locator(
                bootstrap, page_index=1, resource_href="images/not-page-2.png"
            ),
        ),
    )

    assert accepted.status_code == 200
    assert wrong_media_type.status_code == 422
    assert wrong_media_type.json()["error"]["code"] == (
        "READER_LOCATOR_RESOURCE_INVALID"
    )


def test_reader_v4_validates_audio_file_chapter_and_position(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    volume.format = "MP3"
    volume.duration_ms = 60_000
    file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    file.kind = "AUDIO"
    file.mime_type = "audio/mpeg"
    file.duration_ms = 60_000
    chapter = LibraryReadingUnit(
        id="audio-chapter-1",
        volume_id=volume.id,
        file_id=file.id,
        unit_type="chapter",
        title="Chapter 1",
        href="",
        media_type="audio/mpeg",
        sort_order=0,
        start_ms=0,
        end_ms=60_000,
        duration_ms=60_000,
        metadata_json="{}",
    )
    db_session.add(chapter)
    db_session.commit()
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    accepted = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            locator=_exact_audio_locator(
                bootstrap,
                file_id=file.id,
                chapter_id=chapter.id,
                position_millis=42_000,
            ),
        ),
    )
    out_of_range = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(
            bootstrap,
            locator=_exact_audio_locator(
                bootstrap,
                file_id=file.id,
                chapter_id=chapter.id,
                position_millis=60_001,
            ),
        ),
    )

    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["data"]["locator"]["kind"] == "audio"
    assert accepted.json()["data"]["displayPercent"] == 70
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"


def test_reader_v4_rejects_position_only_reflow_anchor(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    locator = _exact_locator(bootstrap)
    locator["engineLocator"]["payload"] = {
        "href": "chapter-1.xhtml",
        "type": "application/xhtml+xml",
        "locations": {"position": 1},
    }
    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, locator=locator),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_NOT_EXACT"


def test_reader_v4_rejects_progress_without_locator(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]

    payload = _progress_payload(bootstrap)
    payload.pop("locator")
    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=payload,
    )

    assert response.status_code == 422
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_rejects_removed_publication_fingerprint_field(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    locator = _exact_locator(bootstrap)
    locator["publication"] = {
        "originalFileHash": f"sha256:{'b' * 64}",
        "parser": "replacement-parser:2",
        "normalization": "replacement-normalization:2",
    }

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, locator=locator),
    )

    assert response.status_code == 422
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_bootstrap_does_not_expose_file_hashes(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")

    assert response.status_code == 200
    bootstrap = response.json()["data"]
    assert bootstrap["volume"]["id"] == volume.id
    assert "publicationFingerprint" not in bootstrap
    assert "contentFingerprint" not in bootstrap
    assert all("contentHash" not in item for item in bootstrap["files"])


@pytest.mark.parametrize(
    "mutate_locator",
    [
        lambda locator: locator["engineLocator"].update({"engine": "foliate"}),
        lambda locator: locator["engineLocator"].update({"platform": "desktop"}),
        lambda locator: locator["engineLocator"]["payload"].update({"href": ""}),
        lambda locator: locator["engineLocator"]["payload"]["text"].update(
            {"highlight": "x" * 513}
        ),
        lambda locator: locator.update({"extra": True}),
    ],
)
def test_reader_v4_rejects_noncanonical_location_payloads(
    client: TestClient,
    db_session: Session,
    mutate_locator: object,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)
    bootstrap = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap").json()[
        "data"
    ]
    locator = _exact_locator(bootstrap)
    assert callable(mutate_locator)
    mutate_locator(locator)
    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/progress",
        json=_progress_payload(bootstrap, locator=locator),
    )

    assert response.status_code == 422
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_rejects_locator_media_type_that_does_not_match_volume(
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
        json=_progress_payload(
            bootstrap,
            locator=_exact_locator(bootstrap, media_type="application/pdf"),
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"
    assert db_session.query(LibraryReadingProgress).count() == 0


def test_reader_v4_rejects_bookmark_kind_that_does_not_match_volume(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    volume = _ebook_volume(db_session)

    response = client.put(
        f"/api/reader/v4/volumes/{volume.id}/bookmarks",
        json={
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
    assert progress.position == "legacy-position"
    assert progress.page == 7
    assert progress.percent == 100
    assert progress.extra == '{"legacy":true}'
    assert progress.location_type == "comic"
    assert progress.location_json == '{"type":"comic","pageIndex":7}'
    assert progress.revision == 0


def test_reader_v4_bootstrap_generates_missing_epub_navigation_once(
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
    source_file.mtime_ms = int(epub.stat().st_mtime * 1000)
    volume.chapter_count = None
    db_session.commit()

    first_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")

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
        second_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    finally:
        event.remove(engine, "before_cursor_execute", capture_writes)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert [unit["title"] for unit in first_response.json()["data"]["units"]] == [
        "第一章",
        "第二章",
    ]
    assert set(first_response.json()["data"]["units"][0]) == {
        "id",
        "index",
        "title",
        "href",
        "fileId",
        "startMs",
        "endMs",
        "durationMs",
        "metadata",
    }
    assert (
        second_response.json()["data"]["units"]
        == first_response.json()["data"]["units"]
    )
    assert writes == []
    assert db_session.query(LibraryReadingUnit).count() == 2
    db_session.refresh(volume)
    assert volume.chapter_count == 2


def test_reader_v4_bootstrap_replaces_legacy_navigation_with_publication_toc(
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
    source_file.mtime_ms = int(epub.stat().st_mtime * 1000)
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
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    stored_units = (
        db_session.query(LibraryReadingUnit)
        .order_by(LibraryReadingUnit.sort_order)
        .all()
    )
    assert [unit.id for unit in stored_units] == [
        response.json()["data"]["units"][0]["id"],
        response.json()["data"]["units"][1]["id"],
    ]
    assert all(unit.id.startswith("pubnav_") for unit in stored_units)
    assert [unit.href for unit in stored_units] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    assert all(
        json.loads(unit.metadata_json)["hrefBase"] == "publication-root"
        for unit in stored_units
    )
    assert all(
        json.loads(unit.metadata_json)["exactNavigation"] is True
        for unit in stored_units
    )
    detail_units_response = client.get(
        f"/api/works/work-reader-v3/volumes/{volume.id}/reading-units",
        params={"page": 1, "pageSize": 120},
    )
    assert detail_units_response.status_code == 200


def test_reader_v2_and_edition_file_routes_are_gone(client: TestClient) -> None:
    assert client.get("/api/reader/v2/editions/legacy/bootstrap").status_code == 404
    assert client.get("/api/editions/legacy/file").status_code == 404


def test_reader_v4_bookmarks_fall_back_from_non_iso_created_at(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    volume = _ebook_volume(db_session)
    fallback_created_at = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)
    db_session.add(
        ReaderBookmark(
            id="reader-v3-legacy-bookmark",
            user_id=user.id,
            volume_id=volume.id,
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
    source_file = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_file.path = "library/reader-v3.epub"
    db_session.commit()

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
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    source = _ebook_volume(db_session)
    source_file = db_session.query(LibraryFile).filter_by(volume_id=source.id).one()
    derived_path = tmp_path / "reader-v3-derived.epub"
    derived_path.write_bytes(Path(source_file.path).read_bytes())
    with zipfile.ZipFile(derived_path, "a") as archive:
        archive.writestr("META-INF/derived-volume", "derived")
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
            path=str(derived_path),
            mtime_ms=2,
            kind="EPUB",
            mime_type="application/epub+zip",
            size_bytes=derived_path.stat().st_size,
            sort_order=0,
        )
    )
    db_session.commit()

    source_bootstrap = client.get(
        f"/api/reader/v4/volumes/{source.id}/bootstrap"
    ).json()["data"]
    source_save = client.put(
        f"/api/reader/v4/volumes/{source.id}/progress",
        json=_progress_payload(
            source_bootstrap,
            locator=_exact_locator(
                source_bootstrap, progression=1, total_progression=1
            ),
        ),
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
        json=_progress_payload(
            derived_bootstrap,
            locator=_exact_locator(
                derived_bootstrap,
                href="OEBPS/chapter1.xhtml",
                progression=1,
                total_progression=1,
            ),
        ),
    )
    assert derived_save.status_code == 200, derived_save.json()
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
        "mutationId",
        "baseRevision",
        "capturedAtEpochMillis",
        "locator",
    }
    components = schema["components"]["schemas"]
    locator_schema = components[request_name]["properties"]["locator"]
    assert locator_schema["discriminator"]["propertyName"] == "kind"
    assert len(locator_schema["oneOf"]) == 4


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
def test_reader_v3_volume_routes_are_removed(
    client: TestClient,
    method: str,
    resource: str,
) -> None:
    response = client.request(method, f"/api/reader/v3/volumes/legacy/{resource}")

    assert response.status_code == 404
