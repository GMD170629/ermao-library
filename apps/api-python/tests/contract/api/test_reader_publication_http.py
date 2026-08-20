from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY


def _login(client: TestClient, db: Session) -> User:
    user = User(
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
) -> LibraryVolume:
    relative_path = Path("library") / "exact.epub"
    source_path = settings.resolved_storage_root / relative_path
    _write_epub(source_path)
    work = LibraryWork(
        library_id="test-library",
        id=f"work-publication{user_suffix}",
        origin="MANUAL",
        title="跨端出版物",
        normalized_title="跨端出版物",
        author="测试作者",
        normalized_author="测试作者",
        tags="[]",
    )
    version = LibraryVersion(
        id=f"version-publication{user_suffix}",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    volume = LibraryVolume(
        id=f"volume-publication{user_suffix}",
        version_id=version.id,
        title="跨端出版物",
        sort_order=0,
        format="EPUB",
        resource_key="manual:publication",
        import_status="COMPLETED",
    )
    source = LibraryFile(
        id=f"file-publication{user_suffix}",
        volume_id=volume.id,
        path=str(relative_path),
        mtime_ms=int(source_path.stat().st_mtime * 1000),
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=source_path.stat().st_size,
        sort_order=0,
    )
    db.add(work)
    db.flush()
    db.add(version)
    db.flush()
    db.add(volume)
    db.flush()
    db.add(source)
    db.commit()
    return volume


def _seed_txt(db: Session, settings: Settings) -> LibraryVolume:
    relative_path = Path("library") / "exact.txt"
    source_path = settings.resolved_storage_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(
        b"\xff\xfe"
        + "序言\r\n第一章 开端\r\n天地 & <宇宙>\r\n第二章\r\n终章".encode("utf-16-le")
    )
    work = LibraryWork(
        library_id="test-library",
        id="work-txt-publication",
        origin="MANUAL",
        title="确定性文本出版物",
        normalized_title="确定性文本出版物",
        author="测试作者",
        normalized_author="测试作者",
        tags="[]",
    )
    version = LibraryVersion(
        id="version-txt-publication",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    volume = LibraryVolume(
        id="volume-txt-publication",
        version_id=version.id,
        title=work.title,
        sort_order=0,
        format="TXT",
        resource_key="manual:txt-publication",
        import_status="COMPLETED",
    )
    source = LibraryFile(
        id="file-txt-publication",
        volume_id=volume.id,
        path=str(relative_path),
        mtime_ms=int(source_path.stat().st_mtime * 1000),
        kind="TXT",
        mime_type="text/plain",
        size_bytes=source_path.stat().st_size,
        sort_order=0,
    )
    db.add(work)
    db.flush()
    db.add(version)
    db.flush()
    db.add(volume)
    db.flush()
    db.add(source)
    db.commit()
    return volume


def test_epub_publication_requires_authentication(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    volume = _seed_epub(db_session, test_settings)

    response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
    )

    assert response.status_code == 401


def test_epub_publication_exposes_stable_rwpm_and_private_resources(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    volume = _seed_epub(db_session, test_settings)

    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
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
    source = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    assert runtime["sourceSizeBytes"] == source.size_bytes
    assert runtime["sourceMtimeMs"] == source.mtime_ms

    resource_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/OEBPS/Text/chapter.xhtml"
    )
    assert resource_response.status_code == 200
    assert resource_response.headers["cache-control"] == "private, no-cache"
    assert "default-src 'none'" in resource_response.headers["content-security-policy"]
    source_path = test_settings.resolved_storage_root / source.path
    with zipfile.ZipFile(source_path) as archive:
        assert resource_response.content == archive.read("OEBPS/Text/chapter.xhtml")
    assert 'data-shuku-security-profile="web-v2"' not in resource_response.text
    assert "天地玄黄" in resource_response.text

    head_response = client.head(
        f"/api/reader/v4/volumes/{volume.id}/publication/OEBPS/Text/chapter.xhtml"
    )
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert int(head_response.headers["content-length"]) == len(
        resource_response.content
    )

    positions_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/positions.json"
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


def test_work_detail_and_reader_manifest_share_publication_navigation(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    volume = _seed_epub(db_session, test_settings)
    assert db_session.query(LibraryReadingUnit).count() == 0

    detail_response = client.get("/api/works/work-publication")
    units_response = client.get(
        f"/api/works/work-publication/volumes/{volume.id}/reading-units"
    )
    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
    )

    assert detail_response.status_code == 200
    detail_volume = detail_response.json()["data"]["book"]["versions"][0]["volumes"][0]
    assert detail_volume["chapterCount"] is None
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
    volume = _seed_epub(db_session, test_settings)
    source = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_path = test_settings.resolved_storage_root / source.path
    source_path.write_bytes(b"not-an-epub")
    source.size_bytes = source_path.stat().st_size
    source.mtime_ms = int(source_path.stat().st_mtime * 1000)
    db_session.add(
        LibraryReadingUnit(
            id="stale-publication-chapter",
            volume_id=volume.id,
            file_id=source.id,
            unit_type="chapter",
            title="过期章节",
            href="stale.xhtml",
            sort_order=0,
            metadata_json="{}",
        )
    )
    volume.chapter_count = 1
    db_session.commit()

    detail_response = client.get("/api/works/work-publication")
    units_response = client.get(
        f"/api/works/work-publication/volumes/{volume.id}/reading-units"
    )

    assert detail_response.status_code == 200
    detail_volume = detail_response.json()["data"]["book"]["versions"][0]["volumes"][0]
    assert detail_volume["chapterCount"] == 1
    assert units_response.status_code == 200
    assert units_response.json()["data"]["units"] == []
    db_session.expire_all()
    assert db_session.get(LibraryReadingUnit, "stale-publication-chapter") is None
    assert db_session.get(LibraryVolume, volume.id).chapter_count is None


def test_reader_bootstrap_does_not_materialize_or_preflight_invalid_publication(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    _login(client, db_session)
    volume = _seed_epub(db_session, test_settings)
    source = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_path = test_settings.resolved_storage_root / source.path
    source_path.write_bytes(b"not-an-epub")
    source.size_bytes = source_path.stat().st_size
    source.mtime_ms = int(source_path.stat().st_mtime * 1000)
    db_session.commit()

    response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
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
    volume = _seed_epub(db_session, test_settings)

    missing = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/OEBPS/not-in-manifest.js"
    )
    traversal = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/%2e%2e/secret"
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
    work = LibraryWork(
        library_id="test-library",
        id="work-mobi-publication",
        origin="MANUAL",
        title="中文字符完整性验证",
        normalized_title="中文字符完整性验证",
        author="测试作者",
        normalized_author="测试作者",
        tags="[]",
    )
    version = LibraryVersion(
        id="version-mobi-publication",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    volume = LibraryVolume(
        id="volume-mobi-publication",
        version_id=version.id,
        title=work.title,
        sort_order=0,
        format="AZW3",
        resource_key="manual:mobi-publication",
        import_status="COMPLETED",
    )
    source = LibraryFile(
        id="file-mobi-publication",
        volume_id=volume.id,
        path="library/exact.azw3",
        mtime_ms=int(target.stat().st_mtime * 1000),
        kind="AZW3",
        mime_type="application/x-mobipocket-ebook",
        size_bytes=target.stat().st_size,
        sort_order=0,
    )
    db_session.add(work)
    db_session.flush()
    db_session.add(version)
    db_session.flush()
    db_session.add(volume)
    db_session.flush()
    db_session.add(source)
    db_session.commit()

    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
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
        f"/api/reader/v4/volumes/{volume.id}/publication/part00000.html"
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
    volume = _seed_txt(db_session, test_settings)
    source = db_session.query(LibraryFile).filter_by(volume_id=volume.id).one()
    source_path = test_settings.resolved_storage_root / source.path
    source_hash_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    bootstrap_response = client.get(f"/api/reader/v4/volumes/{volume.id}/bootstrap")
    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
    )
    units_response = client.get(
        f"/api/works/work-txt-publication/volumes/{volume.id}/reading-units"
    )

    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    publication_access = bootstrap["publication"]
    assert publication_access["manifestUrl"] == (
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
    )
    assert publication_access["positionsUrl"] == (
        f"/api/reader/v4/volumes/{volume.id}/publication/positions.json"
    )
    assert "renderArtifact" not in publication_access
    retired_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/render.epub"
    )
    assert retired_response.status_code == 404
    assert "publicationFingerprint" not in bootstrap
    assert "contentHash" not in bootstrap["files"][0]

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["metadata"]["identifier"] == (
        f"urn:shuku:txt:{source.size_bytes}:{source_path.stat().st_mtime_ns}"
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
        "sourceSizeBytes": source.size_bytes,
        "sourceMtimeMs": source.mtime_ms,
        "parser": "shuku-txt-parser-v1",
        "normalization": "shuku-txt-publication-v2",
        "positionPageLength": 1024,
    }
    assert units_response.status_code == 200
    units = units_response.json()["data"]["units"]
    assert [(unit["title"], unit["href"]) for unit in units] == [
        (entry["title"], entry["href"]) for entry in manifest["toc"]
    ]
    assert all(unit["metadataJson"]["exactNavigation"] is True for unit in units)
    assert all(unit["metadataJson"]["hrefBase"] == "publication-root" for unit in units)

    resource_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/text/chapter-0002.xhtml"
    )
    assert resource_response.status_code == 200
    assert resource_response.headers["content-type"].startswith("application/xhtml+xml")
    assert 'id="heading-000001"' in resource_response.text
    assert 'id="block-000001"' in resource_response.text
    assert "天地 &amp; &lt;宇宙&gt;" in resource_response.text

    positions_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/positions.json"
    )
    assert positions_response.status_code == 200
    assert positions_response.json()["total"] == 3

    missing_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/text/not-indexed.xhtml"
    )
    traversal_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/%2e%2e/secret"
    )
    assert missing_response.status_code == 404
    assert traversal_response.status_code == 404
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash_before
    assert not (
        test_settings.resolved_storage_root / "cache" / "publication-render"
    ).exists()
