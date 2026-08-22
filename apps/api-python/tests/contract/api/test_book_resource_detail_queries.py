"""Contract coverage for the canonical Book/ReadableResource/Asset surface."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.core.auth import hash_password
from app.main import create_app
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
    ReadableResourceNavigationUnit,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.models.organize import MetadataWritebackOperation, OrganizePolicy
from app.modules.metadata.application.opf import parse_opf_metadata
from app.services.metadata_file_writeback import process_next_metadata_writeback


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _source_node(
    node_id: str,
    relative_path: str,
    *,
    physical_kind: str = "REGULAR_FILE",
    size: int | None = 100,
    parent_id: str | None = None,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        parent_id=parent_id,
        parent_physical_kind="DIRECTORY" if parent_id else None,
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=size if physical_kind != "DIRECTORY" else None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _add_book(
    db_session,
    *,
    book_id: str = "detail-book",
    resource_count: int = 3,
) -> tuple[LibraryBook, list[LibraryReadableResource]]:
    book_node = _source_node(
        f"{book_id}-node", f"{book_id}/", physical_kind="DIRECTORY", size=None
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
            title="Detail book",
            normalized_title="detail book",
            author="Author",
        )
    )
    db_session.flush()

    resources: list[LibraryReadableResource] = []
    for index in range(resource_count):
        resource_id = f"detail-resource-{index + 1:02d}"
        relative_path = f"{book_id}/resource-{index + 1:02d}.epub"
        source_node = _source_node(
            f"{resource_id}-node", relative_path, size=(index + 1) * 100
        )
        resource = LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=source_node.id,
            adapter_id="epub-file",
            adapter_version="1",
            media_kind="EBOOK",
            format="EPUB",
            import_state="READY",
        )
        resources.append(resource)
        db_session.add(source_node)
        db_session.flush()
        db_session.add(resource)
        db_session.flush()
        db_session.add(
            LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title=f"Resource {index + 1}",
                resource_index=index + 1,
                chapter_count=index + 2,
            )
        )
        db_session.flush()
        db_session.add(
            LibraryResourceAsset(
                id=f"{resource_id}-asset",
                library_id="test-library",
                resource_id=resource_id,
                source_node_id=source_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
                sequence_index=0,
            )
        )
        db_session.flush()
        db_session.add(
            LibraryResourceAssetMetadata(
                asset_id=f"{resource_id}-asset",
                mime_type="application/epub+zip",
            )
        )
        db_session.flush()
    return book, resources


def _login(client, db_session, *, email: str = "detail@example.com") -> User:
    user = User(
        id=f"user-{email.split('@', 1)[0]}",
        email=email,
        name="Detail reader",
        password_hash=hash_password("detail-password"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "detail-password"},
    )
    assert response.status_code == 200, response.text
    return user


def _png_cover() -> bytes:
    output = BytesIO()
    Image.new("RGB", (40, 60), color=(201, 92, 48)).save(output, format="PNG")
    return output.getvalue()


def test_book_detail_is_bounded_and_projects_resource_assets(
    client, db_session
) -> None:
    user = _login(client, db_session)
    _book, resources = _add_book(db_session, resource_count=12)
    db_session.add(
        ReaderResourceProgress(
            id="detail-progress",
            user_id=user.id,
            resource_id=resources[1].id,
            reader_type="reflowable",
            position="chapter-2",
            percent=42.5,
            extra="{}",
            progressed_at=datetime.now(UTC),
            source_protocol="SHUKU_WEB",
        )
    )
    db_session.commit()

    response = client.get("/api/books/detail-book")
    assert response.status_code == 200, response.text
    payload = response.json()["data"]["book"]
    assert payload["id"] == "detail-book"
    assert payload["title"] == "Detail book"
    assert [item["id"] for item in payload["resources"]] == [
        "detail-resource-01",
        "detail-resource-02",
        "detail-resource-03",
        "detail-resource-04",
        "detail-resource-05",
        "detail-resource-06",
        "detail-resource-07",
        "detail-resource-08",
        "detail-resource-09",
        "detail-resource-10",
        "detail-resource-11",
        "detail-resource-12",
    ]
    selected = next(
        item for item in payload["resources"] if item["id"] == "detail-resource-02"
    )
    assert selected["resourceCompleted"] is False
    assert selected["progress"] == 42.5
    assert selected["assets"][0]["resourceId"] == selected["id"]
    assert selected["assets"][0]["url"] == "/api/assets/detail-resource-02-asset"


def test_book_resource_query_pages_deterministically(client, db_session) -> None:
    _login(client, db_session, email="page@example.com")
    _add_book(db_session, resource_count=5)
    db_session.commit()

    response = client.get(
        "/api/books/detail-book/resources",
        params={"page": 2, "pageSize": 2},
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["bookId"] == "detail-book"
    assert payload["page"] == 2
    assert payload["pageSize"] == 2
    assert payload["total"] == 5
    assert payload["totalPages"] == 3
    assert [item["id"] for item in payload["resources"]] == [
        "detail-resource-03",
        "detail-resource-04",
    ]


def test_book_contents_browses_source_tree_with_resource_overlay(
    client, db_session
) -> None:
    _login(client, db_session, email="contents@example.com")
    book, resources = _add_book(db_session, resource_count=1)
    root_id = book.source_node_id
    folder = _source_node(
        "contents-folder",
        "detail-book/第一卷",
        physical_kind="DIRECTORY",
        size=None,
        parent_id=root_id,
    )
    outside = _source_node(
        "outside-folder", "outside", physical_kind="DIRECTORY", size=None
    )
    db_session.add_all([folder, outside])
    db_session.flush()
    resource_node = db_session.get(LibrarySourceNode, resources[0].source_node_id)
    assert resource_node is not None
    resource_node.parent_id = folder.id
    resource_node.parent_physical_kind = "DIRECTORY"
    resource_node.relative_path = "detail-book/第一卷/resource-01.epub"
    resource_node.path_key = _path_key(resource_node.relative_path)
    db_session.commit()

    root_response = client.get("/api/books/detail-book/contents")
    assert root_response.status_code == 200, root_response.text
    root_payload = root_response.json()["data"]
    assert root_payload["currentSourceNodeId"] == root_id
    assert root_payload["breadcrumbs"] == []
    assert [entry["sourceNodeId"] for entry in root_payload["entries"]] == [folder.id]
    assert root_payload["entries"][0]["kind"] == "FOLDER"
    assert root_payload["entries"][0]["hasChildren"] is True
    assert root_payload["entries"][0]["representativeResourceId"] == resources[0].id

    folder_response = client.get(
        "/api/books/detail-book/contents", params={"sourceNodeId": folder.id}
    )
    assert folder_response.status_code == 200, folder_response.text
    folder_payload = folder_response.json()["data"]
    assert [crumb["sourceNodeId"] for crumb in folder_payload["breadcrumbs"]] == [
        folder.id
    ]
    assert folder_payload["parentSourceNodeId"] == root_id
    assert folder_payload["currentNode"]["title"] == "第一卷"
    assert folder_payload["currentResourceIds"] == [resources[0].id]
    assert folder_payload["entries"][0]["resourceId"] == resources[0].id

    update_response = client.patch(
        f"/api/books/detail-book/source-nodes/{folder.id}",
        json={"title": "彩色珍藏版", "description": "测试版本简介"},
    )
    assert update_response.status_code == 200, update_response.text
    db_session.expire_all()
    metadata = db_session.get(LibrarySourceNodeMetadata, folder.id)
    assert metadata is not None
    assert (metadata.title, metadata.description) == ("彩色珍藏版", "测试版本简介")
    renamed_response = client.get(
        "/api/books/detail-book/contents", params={"sourceNodeId": folder.id}
    )
    assert renamed_response.json()["data"]["currentNode"]["title"] == "彩色珍藏版"

    outside_response = client.get(
        "/api/books/detail-book/contents", params={"sourceNodeId": outside.id}
    )
    assert outside_response.status_code == 404
    assert outside_response.json()["error"]["code"] == "BOOK_CONTENTS_NOT_FOUND"


def test_source_node_edit_respects_opf_setting_and_publishes_its_own_cover(
    client, db_session, test_settings, tmp_path: Path
) -> None:
    _login(client, db_session, email="directory-cover@example.com")
    book, _resources = _add_book(db_session, resource_count=0)
    library_root = tmp_path / "library"
    directory_path = library_root / "detail-book" / "第一卷"
    directory_path.mkdir(parents=True)
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(library_root)
    folder = _source_node(
        "directory-cover-folder",
        "detail-book/第一卷",
        physical_kind="DIRECTORY",
        size=None,
        parent_id=book.source_node_id,
    )
    db_session.add(folder)
    db_session.commit()

    disabled_response = client.patch(
        f"/api/books/{book.id}/source-nodes/{folder.id}",
        json={"title": "关闭写回", "description": "只保存数据库"},
    )
    assert disabled_response.status_code == 200, disabled_response.text
    assert db_session.scalar(select(MetadataWritebackOperation)) is None

    db_session.add(OrganizePolicy(id="default", write_metadata_to_files=True))
    db_session.commit()
    response = client.put(
        f"/api/books/{book.id}/source-nodes/{folder.id}",
        data={"title": "彩色珍藏版", "description": "目录自己的简介"},
        files={"cover": ("directory.png", _png_cover(), "image/png")},
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    metadata = db_session.get(LibrarySourceNodeMetadata, folder.id)
    assert metadata is not None
    assert metadata.title == "彩色珍藏版"
    assert metadata.description == "目录自己的简介"
    assert metadata.cover_status == "READY"
    assert metadata.cover_path == f"covers/source-nodes/{folder.id}.png"
    assert (test_settings.resolved_storage_root / metadata.cover_path).is_file()
    operation = db_session.scalar(select(MetadataWritebackOperation))
    assert operation is not None
    assert operation.source_node_id == folder.id
    assert operation.resource_id is None

    contents = client.get(f"/api/books/{book.id}/contents").json()["data"]
    entry = next(
        item for item in contents["entries"] if item["sourceNodeId"] == folder.id
    )
    assert entry["coverUrl"] == (f"/api/books/{book.id}/source-nodes/{folder.id}/cover")
    cover_response = client.get(entry["coverUrl"])
    assert cover_response.status_code == 200
    assert cover_response.headers["content-type"] == "image/png"

    assert process_next_metadata_writeback(db_session, test_settings) is True
    assert process_next_metadata_writeback(db_session, test_settings) is True
    opf = parse_opf_metadata((directory_path / "metadata.opf").read_bytes())
    assert opf.title == "彩色珍藏版"
    assert opf.description == "目录自己的简介"
    assert (directory_path / "metadata.cover.png").is_file()


def test_reading_units_are_scoped_to_one_book_resource(client, db_session) -> None:
    _login(client, db_session, email="units@example.com")
    _add_book(db_session, resource_count=2)
    db_session.add_all(
        [
            ReadableResourceNavigationUnit(
                id="unit-one",
                resource_id="detail-resource-01",
                unit_type="chapter",
                title="Chapter 1",
                href="chapter-1.xhtml",
                media_type="application/xhtml+xml",
                sort_order=0,
                metadata_json=json.dumps({"chapter": 1}),
            ),
            ReadableResourceNavigationUnit(
                id="unit-two",
                resource_id="detail-resource-02",
                unit_type="chapter",
                title="Other chapter",
                href="other.xhtml",
                media_type="application/xhtml+xml",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/books/detail-book/resources/detail-resource-01/reading-units"
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["bookId"] == "detail-book"
    assert data["resourceId"] == "detail-resource-01"
    assert [unit["id"] for unit in data["units"]] == ["unit-one"]


def test_book_resource_contract_preserves_auth_and_retires_old_routes(
    client, db_session
) -> None:
    _add_book(db_session, resource_count=1)
    db_session.commit()

    assert client.get("/api/books/detail-book").status_code == 401
    assert client.get("/api/books/missing-book").status_code == 401
    assert client.get("/api/works/detail-book").status_code == 404
    assert client.get("/api/books/detail-book/versions").status_code == 404
    assert client.get("/api/resources/missing-resource").status_code == 401
    assert (
        client.get("/api/books/detail-book/resources/missing-resource").status_code
        == 405
    )


def test_openapi_exposes_only_canonical_book_resource_reader_paths() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/books/{book_id}" in paths
    assert "/api/books/{book_id}/resources" in paths
    assert "/api/books/{book_id}/contents" in paths
    assert "/api/resources/{resource_id}" in paths
    assert "/api/reader/v4/resources/{resource_id}/bootstrap" in paths
    assert not any(
        path.startswith("/api/works") or "/versions" in path or "/volumes" in path
        for path in paths
    )
