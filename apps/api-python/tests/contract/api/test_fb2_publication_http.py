from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.config import Settings
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


def test_fb2_publication_manifest_and_resources_use_direct_adapter(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    user = User(
        email="fb2-publication@example.com",
        name="FB2 Publication Reader",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    relative_path = Path("library") / "direct.fb2"
    source_path = test_settings.resolved_storage_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        """<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
        <description><title-info><book-title>直接读取 FB2</book-title><lang>zh-CN</lang>
        </title-info></description><body><section><title><p>第一部</p></title>
        <section><title><p>第一章</p></title><p>正文内容</p></section>
        </section></body></FictionBook>""",
        encoding="utf-8",
    )
    book_node = LibrarySourceNode(
        id="book-fb2-publication-node",
        library_id="test-library",
        relative_path="fb2-publication/",
        path_key=_path_key("fb2-publication/"),
        name="fb2-publication",
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=1_000_000,
        observed_at=datetime.now(UTC),
    )
    source_node = LibrarySourceNode(
        id="asset-fb2-publication-node",
        library_id="test-library",
        relative_path=str(relative_path),
        path_key=_path_key(str(relative_path)),
        name=relative_path.name,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=source_path.stat().st_size,
        observed_mtime_ns=int(source_path.stat().st_mtime * 1_000_000_000),
        observed_at=datetime.now(UTC),
    )
    book = LibraryBook(
        id="book-fb2-publication",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    book_metadata = LibraryBookMetadata(
        book_id=book.id,
        title="直接读取 FB2",
        normalized_title="直接读取 fb2",
    )
    resource = LibraryReadableResource(
        id="resource-fb2-publication",
        library_id="test-library",
        book_id=book.id,
        source_node_id=source_node.id,
        adapter_id="fb2",
        adapter_version="1",
        media_kind="READABLE",
        format="FB2",
        enablement_state="ENABLED",
        import_state="READY",
    )
    resource_metadata = LibraryReadableResourceMetadata(
        resource_id=resource.id,
        title=book_metadata.title,
    )
    asset = LibraryResourceAsset(
        id="asset-fb2-publication",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=source_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
        sequence_index=0,
        sort_key="0",
    )
    asset_metadata = LibraryResourceAssetMetadata(
        asset_id=asset.id,
        mime_type="application/x-fictionbook+xml",
    )
    db_session.add_all(
        [
            user,
            book_node,
            source_node,
            book,
            book_metadata,
            resource,
            resource_metadata,
            asset,
            asset_metadata,
        ]
    )
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert login.status_code == 200

    manifest_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/manifest.json"
    )

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["metadata"]["title"] == "直接读取 FB2"
    assert manifest["readingOrder"] == [
        {
            "href": "fb2/section-0001.xhtml",
            "type": "application/xhtml+xml",
            "title": "第一部",
        }
    ]
    assert manifest["toc"][0]["title"] == "第一部"
    assert manifest["toc"][0]["children"][0]["title"] == "第一章"
    assert manifest["https://shuku.app/reader/runtime"] == {
        "sourceSizeBytes": source_path.stat().st_size,
        "sourceMtimeMs": int(source_path.stat().st_mtime * 1000),
        "parser": "shuku-fb2-parser-v1",
        "normalization": "shuku-fb2-publication-v1",
        "positionPageLength": 1024,
    }

    resource_response = client.get(
        f"/api/reader/v4/resources/{resource.id}/publication/fb2/section-0001.xhtml"
    )
    assert resource_response.status_code == 200
    assert "正文内容" in resource_response.text
    assert 'data-shuku-security-profile="web-v2"' in resource_response.text
