from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings
from app.models import ReadableResourceNavigationUnit
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


def _path_key(path: str) -> str:
    return f"v1:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _login(client: TestClient, db: Session) -> User:
    user = User(
        id="publication-reader-user",
        email="publication-reader@example.com",
        name="Publication Reader",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db.add(user)
    db.commit()
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
    size_bytes: int | None,
    mtime_ms: int = 1,
    physical_kind: str = "REGULAR_FILE",
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


def _seed_resource(
    db: Session,
    *,
    resource_id: str,
    book_id: str,
    path: str,
    title: str,
    fmt: str,
    mime_type: str,
) -> LibraryReadableResource:
    source = Path(path)
    mtime_ms = int(source.stat().st_mtime * 1000)
    book_node = _source_node(
        f"{book_id}-node",
        f"{book_id}/",
        size_bytes=None,
        physical_kind="DIRECTORY",
    )
    source_node = _source_node(
        f"{resource_id}-node",
        path,
        size_bytes=source.stat().st_size,
        mtime_ms=mtime_ms,
    )
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book_id,
        title=title,
        normalized_title=title.lower(),
        author="测试作者",
        normalized_author="测试作者",
    )
    resource = LibraryReadableResource(
        id=resource_id,
        library_id="test-library",
        book_id=book_id,
        source_node_id=source_node.id,
        adapter_id=fmt.lower(),
        adapter_version="1",
        media_kind=(
            "COMIC"
            if fmt.upper() in {"CBZ", "ZIP", "CBR", "RAR"}
            else "AUDIOBOOK"
            if fmt.upper() in {"AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3"}
            else "EBOOK"
        ),
        format=fmt,
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource_id,
        title=title,
    )
    asset = LibraryResourceAsset(
        id=f"{resource_id}-asset",
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
        asset_id=asset.id,
        mime_type=mime_type,
    )
    db.add_all([book_node, source_node])
    db.flush()
    db.add(book)
    db.flush()
    db.add(book_metadata)
    db.flush()
    db.add(resource)
    db.flush()
    db.add(resource_metadata)
    db.flush()
    db.add(asset)
    db.flush()
    db.add(asset_metadata)
    db.commit()
    return resource


def _write_epub(path: Path) -> None:
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
            """<package xmlns:dc="http://purl.org/dc/elements/1.1/">
            <metadata><dc:title>跨端出版物</dc:title><dc:creator>测试作者</dc:creator>
            <dc:language>zh-CN</dc:language></metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
            properties="nav"/>
            <item id="chapter" href="Text/chapter.xhtml"
            media-type="application/xhtml+xml"/>
            <item id="style" href="Styles/book.css" media-type="text/css"/>
            </manifest><spine><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
            xmlns:epub="http://www.idpf.org/2007/ops"><body>
            <nav epub:type="toc"><ol><li>
            <a href="Text/chapter.xhtml#anchor">第一章</a>
            </li></ol></nav>
            </body></html>""",
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
            <link rel="stylesheet" href="../Styles/book.css"/></head>
            <body><h1 id="anchor">第一章</h1><p>天地玄黄，宇宙洪荒</p></body></html>""",
        )
        archive.writestr("OEBPS/Styles/book.css", "body { line-height: 1.6; }")


def _seed_epub(
    db: Session,
    settings: Settings,
    *,
    user_suffix: str = "",
) -> LibraryReadableResource:
    relative_path = Path("library") / f"exact{user_suffix}.epub"
    source_path = settings.resolved_storage_root / relative_path
    _write_epub(source_path)
    return _seed_resource(
        db,
        resource_id=f"resource-publication{user_suffix}",
        book_id=f"book-publication{user_suffix}",
        path=str(source_path),
        title="跨端出版物",
        fmt="EPUB",
        mime_type="application/epub+zip",
    )


def _seed_txt(db: Session, settings: Settings) -> LibraryReadableResource:
    relative_path = Path("library") / "exact.txt"
    source_path = settings.resolved_storage_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(
        b"\xff\xfe"
        + "序言\r\n第一章 开端\r\n天地 & <宇宙>\r\n第二章\r\n终章".encode("utf-16-le")
    )
    return _seed_resource(
        db,
        resource_id="resource-txt-publication",
        book_id="book-txt-publication",
        path=str(source_path),
        title="确定性文本出版物",
        fmt="TXT",
        mime_type="text/plain",
    )


def test_epub_publication_requires_authentication(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    resource = _seed_epub(db_session, test_settings)

    response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )

    assert response.status_code == 401


def test_epub_publication_exposes_stable_rwpm_and_private_resources(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_epub(db_session, test_settings)

    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["metadata"]["title"] == "跨端出版物"
    assert manifest["readingOrder"] == [
        {"href": "OEBPS/Text/chapter.xhtml", "type": "application/xhtml+xml"}
    ]
    assert manifest["toc"][0] == {
        "href": "OEBPS/Text/chapter.xhtml#anchor",
        "title": "第一章",
    }
    runtime = manifest["https://shuku.app/reader/runtime"]
    assert runtime["parser"] == "epub-package:1"
    assert runtime["normalization"] == "shuku-epub-locator-dom-v2"
    source_path = test_settings.resolved_storage_root / "library/exact.epub"
    assert runtime["sourceSizeBytes"] == source_path.stat().st_size
    assert runtime["sourceMtimeMs"] == int(source_path.stat().st_mtime * 1000)

    resource_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/OEBPS/Text/chapter.xhtml"
    )
    assert resource_response.status_code == 200
    assert resource_response.headers["cache-control"] == "private, no-cache"
    assert "default-src 'none'" in resource_response.headers["content-security-policy"]
    with zipfile.ZipFile(source_path) as archive:
        assert resource_response.content == archive.read("OEBPS/Text/chapter.xhtml")
    assert 'data-shuku-security-profile="web-v2"' not in resource_response.text
    assert "天地玄黄" in resource_response.text

    head_response = client.head(
        f"/api/reader/v4/resources/{resource.id}/publication/OEBPS/Text/chapter.xhtml"
    )
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert int(head_response.headers["content-length"]) == len(
        resource_response.content
    )

    positions_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/positions.json"
    )
    assert positions_response.status_code == 200
    assert positions_response.json() == {
        "total": 1,
        "positions": [
            {
                "href": "OEBPS/Text/chapter.xhtml",
                "type": "application/xhtml+xml",
                "locations": {
                    "position": 1,
                    "progression": 0.0,
                    "totalProgression": 0.0,
                },
            }
        ],
    }


def test_book_detail_and_reader_manifest_share_publication_navigation(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_epub(db_session, test_settings)
    assert db_session.query(ReadableResourceNavigationUnit).count() == 0

    detail_response = client.get("/api/books/book-publication")
    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )
    units_response = client.get(
        f"/api/books/book-publication/resources/{resource.id}/reading-units"
    )

    assert detail_response.status_code == 200
    detail_resource = detail_response.json()["data"]["book"]["resources"][0]
    assert detail_resource["chapterCount"] is None
    assert units_response.status_code == 200
    units = units_response.json()["data"]["units"]
    assert [(unit["title"], unit["href"]) for unit in units] == [
        ("第一章", "OEBPS/Text/chapter.xhtml#anchor")
    ]
    assert all(unit["id"].startswith("pubnav_") for unit in units)
    assert manifest_response.status_code == 200
    toc = manifest_response.json()["toc"]
    assert [(entry["title"], entry["href"]) for entry in toc] == [
        (unit["title"], unit["href"]) for unit in units
    ]


def test_corrupt_publication_detail_clears_stale_chapters_and_stays_available(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_epub(db_session, test_settings)
    source_path = test_settings.resolved_storage_root / "library/exact.epub"
    source_path.write_bytes(b"not-an-epub")
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.observed_size_bytes = source_path.stat().st_size
    source_node.observed_mtime_ns = int(source_path.stat().st_mtime * 1000) * 1_000_000
    db_session.add(
        ReadableResourceNavigationUnit(
            id="stale-publication-chapter",
            resource_id=resource.id,
            asset_id=f"{resource.id}-asset",
            unit_type="chapter",
            title="过期章节",
            href="stale.xhtml",
            sort_order=0,
            metadata_json="{}",
        )
    )
    resource_metadata = db_session.get(LibraryReadableResourceMetadata, resource.id)
    assert resource_metadata is not None
    resource_metadata.chapter_count = 1
    db_session.commit()

    detail_response = client.get("/api/books/book-publication")
    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )
    db_session.expire_all()
    units_response = client.get(
        f"/api/books/book-publication/resources/{resource.id}/reading-units"
    )

    assert detail_response.status_code == 200
    assert manifest_response.status_code == 404
    detail_resource = detail_response.json()["data"]["book"]["resources"][0]
    assert detail_resource["chapterCount"] == 1
    assert units_response.status_code == 200
    assert units_response.json()["data"]["units"] == []
    db_session.expire_all()
    assert (
        db_session.get(ReadableResourceNavigationUnit, "stale-publication-chapter")
        is None
    )
    assert (
        db_session.get(LibraryReadableResourceMetadata, resource.id).chapter_count
        is None
    )


def test_reader_bootstrap_does_not_materialize_or_preflight_invalid_publication(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_epub(db_session, test_settings)
    source_path = test_settings.resolved_storage_root / "library/exact.epub"
    source_path.write_bytes(b"not-an-epub")
    source_node = db_session.get(LibrarySourceNode, f"{resource.id}-node")
    assert source_node is not None
    source_node.observed_size_bytes = source_path.stat().st_size
    source_node.observed_mtime_ns = int(source_path.stat().st_mtime * 1000) * 1_000_000
    db_session.commit()

    response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")
    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )

    assert response.status_code == 200
    assert "renderArtifact" not in response.json()["data"]["publication"]
    assert manifest_response.status_code == 404


def test_epub_publication_rejects_unindexed_and_traversal_resources(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_epub(db_session, test_settings)

    missing = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/OEBPS/not-in-manifest.js"
    )
    traversal = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/%2e%2e/secret"
    )

    assert missing.status_code == 404
    assert traversal.status_code == 404


def test_mobi_publication_uses_pinned_runtime_without_materializing_epub(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    fixture = (
        Path(__file__).parents[5] / "test-data" / "library" / "mobi" / "08-zh-hans.azw3"
    )
    target = test_settings.resolved_storage_root / "library" / "exact.azw3"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, target)
    source_hash_before = hashlib.sha256(target.read_bytes()).hexdigest()
    resource = _seed_resource(
        db_session,
        resource_id="resource-mobi-publication",
        book_id="book-mobi-publication",
        path=str(target),
        title="中文字符完整性验证",
        fmt="AZW3",
        mime_type="application/x-mobipocket-ebook",
    )

    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["readingOrder"][0]["href"] == "part00000.html"
    assert manifest["readingOrder"][0]["type"] == "text/html"
    runtime = manifest["https://shuku.app/reader/runtime"]
    assert runtime == {
        "sourceSizeBytes": target.stat().st_size,
        "sourceMtimeMs": int(target.stat().st_mtime * 1000),
        "parser": "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add",
        "normalization": "ermao-mobi-core-v1+shuku-locator-dom-v2",
        "positionPageLength": 1024,
    }
    resource_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/part00000.html"
    )
    assert resource_response.status_code == 200
    assert resource_response.headers["content-type"].startswith("text/html")
    assert "天地玄黄" in resource_response.text
    assert hashlib.sha256(target.read_bytes()).hexdigest() == source_hash_before
    assert not list(test_settings.resolved_storage_root.rglob("*.epub"))
    assert not (
        test_settings.resolved_storage_root / "cache" / "publication-render"
    ).exists()


def test_txt_publication_exposes_deterministic_rwpm_and_normalized_resources(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    resource = _seed_txt(db_session, test_settings)
    source_path = test_settings.resolved_storage_root / "library/exact.txt"
    source_hash_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    bootstrap_response = client.get(f"/api/reader/v4/resources/{resource.id}/bootstrap")
    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )
    units_response = client.get(
        f"/api/books/book-txt-publication/resources/{resource.id}/reading-units"
    )

    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    publication_access = bootstrap["publication"]
    assert publication_access["manifestUrl"] == (
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )
    assert publication_access["positionsUrl"] == (
        f"/api/reader/v4/resources/{resource.id}/publication/positions.json"
    )
    assert "renderArtifact" not in publication_access
    retired_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/render.epub"
    )
    assert retired_response.status_code == 404
    assert "publicationFingerprint" not in bootstrap
    assert all("contentHash" not in item for item in bootstrap["assets"])

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["metadata"]["identifier"] == (
        f"urn:shuku:txt:{source_path.stat().st_size}:{source_path.stat().st_mtime_ns}"
    )
    assert manifest["metadata"]["title"] == "确定性文本出版物"
    assert manifest["metadata"]["author"] == "测试作者"
    assert manifest["metadata"]["readingProgression"] == "ltr"
    assert manifest["readingOrder"] == [
        {
            "href": "text/chapter-0001.xhtml",
            "type": "application/xhtml+xml",
            "title": "确定性文本出版物 1",
        },
        {
            "href": "text/chapter-0002.xhtml",
            "type": "application/xhtml+xml",
            "title": "第一章 开端",
        },
        {
            "href": "text/chapter-0003.xhtml",
            "type": "application/xhtml+xml",
            "title": "第二章",
        },
    ]
    assert manifest["https://shuku.app/reader/runtime"] == {
        "sourceSizeBytes": source_path.stat().st_size,
        "sourceMtimeMs": int(source_path.stat().st_mtime * 1000),
        "parser": "shuku-txt-parser-v1",
        "normalization": "shuku-txt-publication-v2",
        "positionPageLength": 1024,
    }
    assert units_response.status_code == 200
    units = units_response.json()["data"]["units"]
    assert [(unit["title"], unit["href"]) for unit in units] == [
        (entry["title"], entry["href"]) for entry in manifest["toc"]
    ]
    assert all(
        json.loads(unit["metadataJson"])["exactNavigation"] is True for unit in units
    )
    assert all(
        json.loads(unit["metadataJson"])["hrefBase"] == "publication-root"
        for unit in units
    )

    resource_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/text/chapter-0002.xhtml"
    )
    assert resource_response.status_code == 200
    assert resource_response.headers["content-type"].startswith("application/xhtml+xml")
    assert 'id="heading-000001"' in resource_response.text
    assert 'id="block-000001"' in resource_response.text
    assert "天地 &amp; &lt;宇宙&gt;" in resource_response.text

    positions_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/positions.json"
    )
    assert positions_response.status_code == 200
    assert positions_response.json()["total"] == 3

    missing_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/text/not-indexed.xhtml"
    )
    traversal_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/%2e%2e/secret"
    )
    assert missing_response.status_code == 404
    assert traversal_response.status_code == 404
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash_before
    assert not (
        test_settings.resolved_storage_root / "cache" / "publication-render"
    ).exists()
