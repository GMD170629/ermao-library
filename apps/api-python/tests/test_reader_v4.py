from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import ReadableResourceNavigationUnit, ReaderBookmark, ReaderResourceProgress
from app.models.auth import User
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.publications.infrastructure.models import PublicationNavigationCache


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _login(client: TestClient, db_session: Session) -> User:
    user = User(
        id="reader-v4-user",
        email="reader-v4@example.com",
        name="Reader v4",
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


def _source_node(
    node_id: str,
    path: str,
    *,
    physical_kind: str,
    size_bytes: int | None,
    mtime_ms: int = 1,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key=_path_key(path),
        name=Path(path).name or node_id,
        physical_kind=physical_kind,
        observed_size_bytes=size_bytes if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=mtime_ms * 1_000_000,
        observed_at=datetime.now(UTC),
    )


def _add_resource(
    db_session: Session,
    *,
    book_id: str,
    resource_id: str,
    asset_id: str,
    source_path: Path | str,
    title: str = "电子书",
    fmt: str = "EPUB",
    mime_type: str = "application/epub+zip",
    resource_index: float | None = None,
    page_count: int | None = None,
    duration_ms: int | None = None,
) -> tuple[LibraryReadableResource, LibraryResourceAsset]:
    source = Path(source_path)
    path = str(source)
    exists = source.is_file()
    size_bytes = source.stat().st_size if exists else 4
    mtime_ms = source.stat().st_mtime_ns // 1_000_000 if exists else 1
    book = db_session.get(LibraryBook, book_id)
    if book is None:
        book_node = _source_node(
            f"{book_id}-node",
            f"{book_id}/",
            physical_kind="DIRECTORY",
            size_bytes=None,
        )
        book = LibraryBook(
            id=book_id,
            library_id="test-library",
            source_node_id=book_node.id,
        )
        db_session.add(book_node)
        db_session.flush()
        db_session.add(book)
        db_session.flush()
        db_session.add(
            LibraryBookMetadata(
                book_id=book_id,
                title="Reader v4",
                normalized_title="reader v4",
                author="测试作者",
                normalized_author="测试作者",
            )
        )
        db_session.flush()
    elif db_session.get(LibraryBookMetadata, book_id) is None:
        db_session.add(
            LibraryBookMetadata(
                book_id=book_id,
                title="Reader v4",
                normalized_title="reader v4",
                author="测试作者",
                normalized_author="测试作者",
            )
        )
        db_session.flush()
    source_node = _source_node(
        f"{resource_id}-node",
        path,
        physical_kind="REGULAR_FILE",
        size_bytes=size_bytes,
        mtime_ms=mtime_ms,
    )
    media_kind = (
        "COMIC"
        if fmt.upper() in {"CBZ", "ZIP", "CBR", "RAR"}
        else "AUDIOBOOK"
        if fmt.upper() in {"AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3"}
        else "EBOOK"
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book_id,
        source_node_id=source_node.id,
        adapter_id=fmt.lower(),
        adapter_version="1",
        media_kind=media_kind,
        format=fmt,
        enablement_state="ENABLED",
        import_state="READY",
    )
    metadata = LibraryReadableResourceMetadata(
        resource_id=resource_id,
        title=title,
        resource_index=resource_index,
        page_count=page_count,
        duration_ms=duration_ms,
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
        mime_type=mime_type,
        duration_ms=duration_ms,
    )
    db_session.add(source_node)
    db_session.flush()
    db_session.add(resource)
    db_session.flush()
    db_session.add(metadata)
    db_session.flush()
    db_session.add(asset)
    db_session.flush()
    db_session.add(asset_metadata)
    db_session.commit()
    return resource, asset


def _ebook_resource(db_session: Session) -> tuple[LibraryReadableResource, LibraryResourceAsset]:
    source_path = (
        Path(__file__).parents[3] / "test-data" / "library" / "epub" / "reader-v2.epub"
    )
    return _add_resource(
        db_session,
        book_id="book-reader-v4",
        resource_id="resource-reader-v4",
        asset_id="asset-reader-v4",
        source_path=source_path,
        title="电子书",
        resource_index=1,
    )


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
            </manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
            xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head>
            <body><nav epub:type="toc"><ol>
            <li><a href="Text/one.xhtml#start">第一章</a></li>
            <li><a href="Text/two.xhtml">第二章</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/one.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head>
            <body><h1 id="start">第一章</h1></body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/two.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第二章</title></head>
            <body><h1>第二章</h1></body></html>""",
        )


def _exact_locator(
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


def _exact_pdf_locator(*, page_index: int, page_progression: float) -> dict[str, object]:
    return {
        "kind": "pdf",
        "pageIndex": page_index,
        "pageProgression": page_progression,
    }


def _exact_comic_locator(*, page_index: int, resource_href: str) -> dict[str, object]:
    return {
        "kind": "comic",
        "pageIndex": page_index,
        "resourceHref": resource_href,
    }


def _exact_audio_locator(
    *, asset_id: str, chapter_id: str | None, position_millis: int
) -> dict[str, object]:
    locator: dict[str, object] = {
        "kind": "audio",
        "assetId": asset_id,
        "positionMillis": position_millis,
    }
    if chapter_id is not None:
        locator["chapterId"] = chapter_id
    return locator


def _progress_payload(
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
        "locator": locator or _exact_locator(),
    }


def test_reader_v4_bootstrap_and_progress_are_resource_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)

    bootstrap_response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["schemaVersion"] == 4
    assert bootstrap["progressSnapshot"] is None
    empty_progress_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/progress"
    )
    assert empty_progress_response.status_code == 200
    assert empty_progress_response.headers["etag"] == '"reader-progress-0"'
    assert empty_progress_response.json()["data"] == {
        "schemaVersion": 4,
        "progressSnapshot": None,
    }
    assert bootstrap["book"]["id"] == "book-reader-v4"
    assert bootstrap["resource"]["id"] == resource.id
    assert bootstrap["resource"]["bookId"] == "book-reader-v4"
    assert bootstrap["resource"]["resourceCompleted"] is False
    assert bootstrap["availableResources"][0]["id"] == resource.id
    assert "mediaVersion" not in bootstrap
    assert "mediaCompleted" not in bootstrap
    assert "edition" not in bootstrap
    assert bootstrap["sourceFormat"] == "epub"
    assert "publicationFingerprint" not in bootstrap
    assert "contentFingerprint" not in bootstrap
    assert all("contentHash" not in asset for asset in bootstrap["assets"])

    mutation_id = str(uuid4())
    progress_response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(mutation_id=mutation_id),
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
    stored = db_session.query(ReaderResourceProgress).one()
    assert stored.user_id == user.id
    assert stored.resource_id == resource.id
    assert stored.percent == 50
    assert stored.location_json is not None
    assert stored.revision == 1
    assert stored.mutation_id == mutation_id
    initial_bootstrap = client.get(
        f"/api/reader/v4/resources/{resource.id}/bootstrap"
    ).json()["data"]
    assert initial_bootstrap["progressSnapshot"] == progress

    progress_query = client.get(f"/api/reader/v4/resources/{resource.id}/progress")
    assert progress_query.status_code == 200
    assert progress_query.headers["etag"] == '"reader-progress-1"'
    assert progress_query.json()["data"] == {
        "schemaVersion": 4,
        "progressSnapshot": progress,
    }
    unchanged = client.get(
        f"/api/reader/v4/resources/{resource.id}/progress",
        headers={"If-None-Match": progress_query.headers["etag"]},
    )
    assert unchanged.status_code == 304
    assert unchanged.content == b""

    stale_response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            base_revision=0,
            locator=_exact_locator(
                progression=0.1, total_progression=0.1, platform="ios"
            ),
        ),
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "READER_PROGRESS_CONFLICT"
    assert stale_response.json()["error"]["current"] == progress
    db_session.expire_all()
    stored = db_session.query(ReaderResourceProgress).one()
    assert stored.percent == 50
    assert stored.revision == 1
    resumed = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap").json()[
        "data"
    ]["progressSnapshot"]
    assert resumed == progress

    repeated = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(base_revision=0, mutation_id=mutation_id),
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"] == progress


def test_reader_v4_exact_save_after_reading_status_uses_current_revision(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    finished = client.put(
        f"/api/reader/v4/resources/{resource.id}/reading-status",
        json={"status": "FINISHED"},
    )
    assert finished.status_code == 200
    bootstrap = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap").json()[
        "data"
    ]
    saved = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(base_revision=1),
    )

    assert saved.status_code == 200, saved.json()
    assert saved.json()["data"]["revision"] == 2
    progress = db_session.query(ReaderResourceProgress).one()
    assert progress.location_type == "reflowable"
    assert progress.revision == 2
    assert bootstrap["resource"]["resourceCompleted"] is True


def test_reader_v4_validates_pdf_progress_against_canonical_page_index(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    resource, asset = _ebook_resource(db_session)
    resource.format = "PDF"
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    metadata.page_count = 12
    asset_metadata = db_session.get(LibraryResourceAssetMetadata, asset.id)
    assert asset_metadata is not None
    asset_metadata.mime_type = "application/pdf"
    db_session.commit()
    bootstrap = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap").json()[
        "data"
    ]
    assert bootstrap["sourceFormat"] == "pdf"
    assert bootstrap["readerType"] == "pdf"
    assert bootstrap["resource"]["bookId"] == "book-reader-v4"
    assert "mediaKind" not in bootstrap["book"]

    nullable_locator = _exact_pdf_locator(page_index=2, page_progression=0.25)
    nullable_locator["engineLocator"] = None
    explicit_null = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(locator=nullable_locator),
    )
    assert explicit_null.status_code == 422

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_pdf_locator(page_index=2, page_progression=0.25)
        ),
    )

    assert response.status_code == 200
    assert "engineLocator" not in response.json()["data"]["locator"]

    out_of_range = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            base_revision=1,
            locator=_exact_pdf_locator(page_index=12, page_progression=0.25),
        ),
    )
    assert out_of_range.status_code == 422
    assert out_of_range.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"


def test_reader_v4_validates_comic_progress_against_indexed_page_media_type(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, asset = _ebook_resource(db_session)
    resource.format = "CBZ"
    resource.media_kind = "COMIC"
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    metadata.page_count = 2
    asset_metadata = db_session.get(LibraryResourceAssetMetadata, asset.id)
    assert asset_metadata is not None
    asset_metadata.mime_type = "application/vnd.comicbook+zip"
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id=f"comic-page-{page_number}",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="page",
                title=f"Page {page_number + 1}",
                href=f"images/{page_number + 1:04}.jpg",
                media_type="image/jpeg",
                sort_order=page_number,
                metadata_json="{}",
            )
            for page_number in (0, 1)
        ]
    )
    db_session.commit()
    book_response = client.get("/api/books/book-reader-v4")
    assert book_response.status_code == 200, book_response.text
    book_resource = next(
        item
        for item in book_response.json()["data"]["book"]["resources"]
        if item["id"] == resource.id
    )
    assert book_resource["format"] == "CBZ"
    assert book_resource["readerType"] == "comic"
    assert book_resource["mediaKind"] == "COMIC"

    accepted = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_comic_locator(
                page_index=1, resource_href="images/0002.jpg"
            )
        ),
    )
    wrong_media_type = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_comic_locator(
                page_index=1, resource_href="images/not-page-2.png"
            )
        ),
    )

    assert accepted.status_code == 200
    assert wrong_media_type.status_code == 422
    assert wrong_media_type.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"


def test_reader_v4_validates_audio_asset_chapter_and_position(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    source_path = Path(__file__).parent / "reader-audio.mp3"
    resource, asset = _add_resource(
        db_session,
        book_id="book-reader-audio",
        resource_id="resource-reader-audio",
        asset_id="asset-reader-audio",
        source_path=source_path,
        fmt="MP3",
        mime_type="audio/mpeg",
        title="有声书",
        duration_ms=60_000,
    )
    chapter = ReadableResourceNavigationUnit(
        id="audio-chapter-1",
        resource_id=resource.id,
        asset_id=asset.id,
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
    bootstrap = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap").json()[
        "data"
    ]

    accepted = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_audio_locator(
                asset_id=asset.id,
                chapter_id=chapter.id,
                position_millis=42_000,
            )
        ),
    )
    out_of_range = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_audio_locator(
                asset_id=asset.id,
                chapter_id=chapter.id,
                position_millis=60_001,
            )
        ),
    )

    assert bootstrap["readerType"] == "audio"
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
    resource, _asset = _ebook_resource(db_session)
    locator = _exact_locator()
    locator["engineLocator"]["payload"] = {
        "href": "chapter-1.xhtml",
        "type": "application/xhtml+xml",
        "locations": {"position": 1},
    }
    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(locator=locator),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_NOT_EXACT"


def test_reader_v4_rejects_progress_without_locator(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    payload = _progress_payload()
    payload.pop("locator")
    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress", json=payload
    )

    assert response.status_code == 422
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_reader_v4_rejects_removed_publication_fingerprint_field(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    locator = _exact_locator()
    locator["publication"] = {"parser": "replacement-parser:2"}

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(locator=locator),
    )

    assert response.status_code == 422
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_reader_v4_bootstrap_does_not_expose_asset_hashes(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")

    assert response.status_code == 200
    bootstrap = response.json()["data"]
    assert bootstrap["resource"]["id"] == resource.id
    assert "publicationFingerprint" not in bootstrap
    assert "contentFingerprint" not in bootstrap
    assert all("contentHash" not in item for item in bootstrap["assets"])
    assert "mediaVersion" not in bootstrap
    assert "mediaCompleted" not in bootstrap


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
    resource, _asset = _ebook_resource(db_session)
    locator = _exact_locator()
    assert callable(mutate_locator)
    mutate_locator(locator)
    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(locator=locator),
    )

    assert response.status_code == 422
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_reader_v4_rejects_locator_media_type_that_does_not_match_resource(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/progress",
        json=_progress_payload(
            locator=_exact_locator(media_type="application/pdf")
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATOR_RESOURCE_INVALID"
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_reader_v4_rejects_bookmark_kind_that_does_not_match_resource(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/bookmarks",
        json={
            "bookmarks": [
                {
                    "id": "wrong-format-bookmark",
                    "location": {"kind": "comic", "pageIndex": 1},
                    "label": "Wrong format",
                    "percent": 20,
                    "createdAt": "2026-08-13T00:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "READER_LOCATION_FORMAT_MISMATCH"
    assert db_session.query(ReaderBookmark).count() == 0


def test_resource_reading_status_updates_book_detail_and_isolated_progress(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login(client, db_session)
    first, _first_asset = _ebook_resource(db_session)
    second, _second_asset = _add_resource(
        db_session,
        book_id="book-reader-v4",
        resource_id="resource-reader-v4-2",
        asset_id="asset-reader-v4-2",
        source_path="/tmp/reader-v4-second.epub",
        title="电子书 2",
        resource_index=2,
    )

    finished_response = client.put(
        f"/api/reader/v4/resources/{first.id}/reading-status",
        json={"status": "FINISHED"},
    )

    assert finished_response.status_code == 200
    assert finished_response.json()["data"] == {
        "resourceId": first.id,
        "status": "FINISHED",
        "percent": 100.0,
    }
    detail = client.get("/api/books/book-reader-v4").json()["data"]["book"]
    assert detail["continueResourceId"] == first.id
    assert {item["id"] for item in detail["resources"]} == {first.id, second.id}
    assert next(item for item in detail["resources"] if item["id"] == first.id)[
        "resourceCompleted"
    ] is True
    assert next(item for item in detail["resources"] if item["id"] == second.id)[
        "resourceCompleted"
    ] is False
    progresses = db_session.query(ReaderResourceProgress).all()
    assert [(progress.user_id, progress.resource_id, progress.percent) for progress in progresses] == [
        (user.id, first.id, 100.0)
    ]
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
        f"/api/reader/v4/resources/{first.id}/reading-status",
        json={"status": "UNREAD"},
    )

    assert unread_response.status_code == 200
    assert unread_response.json()["data"]["percent"] == 0.0
    assert db_session.query(ReaderResourceProgress).count() == 0


def test_resource_reading_status_creates_clean_revisioned_progress(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)

    response = client.put(
        f"/api/reader/v4/resources/{resource.id}/reading-status",
        json={"status": "FINISHED"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    progress = db_session.query(ReaderResourceProgress).one()
    assert progress.schema_version == 4
    assert progress.reader_type == "reflowable"
    assert progress.position == "0"
    assert progress.percent == 100
    assert progress.location_type is None
    assert progress.location_json is None
    assert progress.revision == 1


def test_reader_v4_bootstrap_generates_missing_epub_navigation_once(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    epub = tmp_path / "without-units.epub"
    _write_reader_epub(epub)
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.relative_path = str(epub)
    source_node.path_key = _path_key(str(epub))
    source_node.name = epub.name
    source_node.observed_size_bytes = epub.stat().st_size
    source_node.observed_mtime_ns = (
        epub.stat().st_mtime_ns // 1_000_000
    ) * 1_000_000
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    metadata.chapter_count = None
    db_session.commit()

    first_response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")

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
        second_response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")
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
        "assetId",
        "startMs",
        "endMs",
        "durationMs",
        "metadata",
    }
    assert second_response.json()["data"]["units"] == first_response.json()["data"]["units"]
    assert writes == []
    assert db_session.query(ReadableResourceNavigationUnit).count() == 2
    db_session.expire_all()
    navigation_cache = db_session.get(PublicationNavigationCache, resource.id)
    assert navigation_cache is not None
    assert navigation_cache.chapter_count == 2


def test_reader_v4_bootstrap_replaces_stale_navigation_with_publication_toc(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    resource, asset = _ebook_resource(db_session)
    epub = tmp_path / "legacy-relative-hrefs.epub"
    _write_reader_epub(epub)
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.relative_path = str(epub)
    source_node.path_key = _path_key(str(epub))
    source_node.name = epub.name
    source_node.observed_size_bytes = epub.stat().st_size
    source_node.observed_mtime_ns = (
        epub.stat().st_mtime_ns // 1_000_000
    ) * 1_000_000
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id="legacy-unit-one",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="chapter",
                title="第一章",
                href="Text/one.xhtml#start",
                media_type="application/xhtml+xml",
                sort_order=1,
                metadata_json=json.dumps({"idref": "one"}),
            ),
            ReadableResourceNavigationUnit(
                id="legacy-unit-two",
                resource_id=resource.id,
                asset_id=asset.id,
                unit_type="chapter",
                title="第二章",
                href="Text/two.xhtml",
                media_type="application/xhtml+xml",
                sort_order=2,
                metadata_json=json.dumps({"idref": "two"}),
            ),
        ]
    )
    metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert metadata is not None
    metadata.chapter_count = 2
    db_session.commit()

    response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")

    assert response.status_code == 200
    assert [unit["href"] for unit in response.json()["data"]["units"]] == [
        "OEBPS/Text/one.xhtml#start",
        "OEBPS/Text/two.xhtml",
    ]
    stored_units = db_session.scalars(
        select(ReadableResourceNavigationUnit).order_by(
            ReadableResourceNavigationUnit.sort_order
        )
    ).all()
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
    detail_units_response = client.get(
        f"/api/books/book-reader-v4/resources/{resource.id}/reading-units",
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
    resource, _asset = _ebook_resource(db_session)
    fallback_created_at = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)
    db_session.add(
        ReaderBookmark(
            id="reader-v4-bookmark-row",
            user_id=user.id,
            resource_id=resource.id,
            bookmark_id="legacy-created-at",
            location_json=json.dumps(
                {"kind": "reflow", "resourceKey": "chapter-1.xhtml"}
            ),
            label="Legacy timestamp",
            percent=10,
            bookmark_created_at="not-an-iso-timestamp",
            created_at=fallback_created_at,
            updated_at=fallback_created_at,
        )
    )
    db_session.commit()

    response = client.get(f"/api/reader/v4/resources/{resource.id}/bookmarks")

    assert response.status_code == 200
    bookmark = response.json()["data"]["bookmarks"][0]
    assert bookmark["id"] == "legacy-created-at"
    assert datetime.fromisoformat(bookmark["createdAt"]) == fallback_created_at


def test_resource_asset_route_streams_the_selected_asset_only(
    client: TestClient,
    db_session: Session,
    test_settings,
) -> None:
    _login(client, db_session)
    resource, asset = _ebook_resource(db_session)
    stored_file = test_settings.resolved_storage_root / "library" / "reader-v4.epub"
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"reader-v4")
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.relative_path = str(stored_file)
    source_node.path_key = _path_key(str(stored_file))
    source_node.observed_size_bytes = stored_file.stat().st_size
    source_node.observed_mtime_ns = (
        stored_file.stat().st_mtime_ns // 1_000_000
    ) * 1_000_000
    db_session.commit()

    response = client.get(f"/api/assets/{asset.id}")

    assert response.status_code == 200
    assert response.content == b"reader-v4"
    assert response.headers["content-type"] == "application/epub+zip"


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("reader-v4.txt", "text/plain"),
        ("reader-v4.pdf", "application/pdf"),
        ("reader-v4.epub", "application/epub+zip"),
        ("reader-v4.cbz", "application/vnd.comicbook+zip"),
        ("reader-v4.mp3", "audio/mpeg"),
    ],
)
def test_resource_asset_download_mode_uses_attachment_for_every_media_format(
    client: TestClient,
    db_session: Session,
    test_settings,
    filename: str,
    mime_type: str,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    stored_file = test_settings.resolved_storage_root / "library" / filename
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"downloadable")
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.relative_path = str(stored_file)
    source_node.path_key = _path_key(str(stored_file))
    source_node.observed_size_bytes = stored_file.stat().st_size
    source_node.observed_mtime_ns = (
        stored_file.stat().st_mtime_ns // 1_000_000
    ) * 1_000_000
    asset_metadata = db_session.get(LibraryResourceAssetMetadata, "asset-reader-v4")
    assert asset_metadata is not None
    asset_metadata.mime_type = mime_type
    db_session.commit()

    inline_response = client.get(f"/api/resources/{resource.id}/asset")
    download_response = client.get(
        f"/api/resources/{resource.id}/asset", params={"download": "true"}
    )

    assert inline_response.status_code == 200
    assert inline_response.headers["content-disposition"].startswith("inline;")
    assert download_response.status_code == 200
    assert download_response.content == b"downloadable"
    assert download_response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{filename}"
    )


def test_book_cover_route_returns_the_book_cover(
    client: TestClient,
    db_session: Session,
    test_settings,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    book_metadata = db_session.get(LibraryBookMetadata, resource.book_id)
    assert book_metadata is not None
    book_metadata.cover_path = "covers/ebook.jpg"
    db_session.commit()
    cover_root = test_settings.resolved_storage_root / "covers"
    cover_root.mkdir(parents=True, exist_ok=True)
    (cover_root / "ebook.jpg").write_bytes(b"ebook-cover")

    response = client.get(f"/api/books/{resource.book_id}/cover")

    assert response.status_code == 200
    assert response.content == b"ebook-cover"


def test_sibling_resources_keep_independent_progress_and_completion(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    source, _source_asset = _ebook_resource(db_session)
    sibling_path = tmp_path / "reader-v4-sibling.epub"
    sibling_path.write_bytes(
        Path(
            Path(__file__).parents[3]
            / "test-data"
            / "library"
            / "epub"
            / "reader-v2.epub"
        ).read_bytes()
    )
    sibling, _sibling_asset = _add_resource(
        db_session,
        book_id=source.book_id,
        resource_id="resource-reader-v4-sibling",
        asset_id="asset-reader-v4-sibling",
        source_path=sibling_path,
        title="EPUB 第二资源",
        resource_index=2,
    )

    source_bootstrap = client.get(
        f"/api/reader/v4/resources/{source.id}/bootstrap"
    ).json()["data"]
    source_save = client.put(
        f"/api/reader/v4/resources/{source.id}/progress",
        json=_progress_payload(
            locator=_exact_locator(progression=1, total_progression=1)
        ),
    )
    assert source_save.status_code == 200
    assert source_bootstrap["resource"]["resourceCompleted"] is False

    sibling_bootstrap = client.get(
        f"/api/reader/v4/resources/{sibling.id}/bootstrap"
    ).json()["data"]
    sibling_save = client.put(
        f"/api/reader/v4/resources/{sibling.id}/progress",
        json=_progress_payload(
            locator=_exact_locator(
                href="OEBPS/chapter1.xhtml", progression=1, total_progression=1
            )
        ),
    )
    assert sibling_save.status_code == 200, sibling_save.json()
    source_after = client.get(
        f"/api/reader/v4/resources/{source.id}/bootstrap"
    ).json()["data"]
    sibling_after = client.get(
        f"/api/reader/v4/resources/{sibling.id}/bootstrap"
    ).json()["data"]
    assert source_after["resource"]["resourceCompleted"] is True
    assert sibling_after["resource"]["resourceCompleted"] is True
    progresses = db_session.query(ReaderResourceProgress).all()
    assert {progress.resource_id for progress in progresses} == {
        source.id,
        sibling.id,
    }


def test_reader_v4_bootstrap_uses_book_and_resources(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)

    response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")

    assert response.status_code == 200
    bootstrap = response.json()["data"]
    assert bootstrap["book"]["id"] == "book-reader-v4"
    assert bootstrap["resource"]["bookId"] == "book-reader-v4"
    assert bootstrap["readerType"] == "reflowable"
    assert "mediaVersion" not in bootstrap
    assert "mediaCompleted" not in bootstrap
    assert all(
        item["bookId"] == "book-reader-v4" for item in bootstrap["availableResources"]
    )


def test_reader_v4_reader_type_follows_resource_format(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    resource, _asset = _ebook_resource(db_session)
    resource.format = "AUDIO"
    resource.media_kind = "AUDIO"
    db_session.commit()

    bootstrap = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap").json()[
        "data"
    ]

    assert bootstrap["readerType"] == "audio"
    assert bootstrap["sourceFormat"] == "audio"
    assert bootstrap["resource"]["mediaKind"] == "AUDIO"
    assert bootstrap["resource"]["id"] == resource.id


def test_reader_v4_book_completion_is_scoped_to_the_current_book(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    _login(client, db_session)
    current, _current_asset = _ebook_resource(db_session)
    other_path = tmp_path / "other-book.epub"
    _write_reader_epub(other_path)
    other, _other_asset = _add_resource(
        db_session,
        book_id="book-reader-other",
        resource_id="resource-reader-other",
        asset_id="asset-reader-other",
        source_path=other_path,
        title="另一图书",
        resource_index=1,
    )

    finished = client.put(
        f"/api/reader/v4/resources/{other.id}/reading-status",
        json={"status": "FINISHED"},
    )
    assert finished.status_code == 200

    current_bootstrap = client.get(
        f"/api/reader/v4/resources/{current.id}/bootstrap"
    ).json()["data"]
    other_bootstrap = client.get(
        f"/api/reader/v4/resources/{other.id}/bootstrap"
    ).json()["data"]

    assert current_bootstrap["book"]["id"] == "book-reader-v4"
    assert other_bootstrap["book"]["id"] == "book-reader-other"
    assert current_bootstrap["resource"]["resourceCompleted"] is False
    assert other_bootstrap["resource"]["resourceCompleted"] is True
    assert {item["id"] for item in current_bootstrap["availableResources"]} == {
        current.id
    }


def test_reader_v4_openapi_requires_no_edition_or_user_identity(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    path = schema["paths"]["/api/reader/v4/resources/{resource_id}/progress"]["put"]
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
def test_reader_v3_resource_routes_are_removed(
    client: TestClient,
    method: str,
    resource: str,
) -> None:
    response = client.request(method, f"/api/reader/v3/resources/legacy/{resource}")

    assert response.status_code == 404
