from __future__ import annotations

import hashlib
from base64 import b64decode
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.auth import hash_password
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.models.auth import User


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _node(
    node_id: str, relative_path: str, *, directory: bool = False
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 10,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _add_graph(db_session, book_id: str, resource_id: str) -> None:
    book_node = _node(f"{book_id}-node", f"{book_id}/", directory=True)
    resource_node = _node(f"{resource_id}-node", f"{book_id}/{resource_id}.pdf")
    db_session.add_all([book_node, resource_node])
    db_session.flush()
    db_session.add(
        LibraryBook(id=book_id, library_id="test-library", source_node_id=book_node.id)
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book_id,
            title="Action book",
            normalized_title="action book",
            author="Author",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=resource_node.id,
            adapter_id="pdf-file",
            adapter_version="1",
            format="PDF",
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(
            resource_id=resource_id, title="Action resource"
        )
    )
    db_session.flush()
    db_session.add(
        LibraryResourceAsset(
            id=f"{resource_id}-asset",
            library_id="test-library",
            resource_id=resource_id,
            source_node_id=resource_node.id,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db_session.flush()


def _login(client, db_session) -> None:
    db_session.add(
        User(
            id="resource-action-admin",
            email="resource-actions@example.com",
            name="Resource actions admin",
            password_hash=hash_password("resource-actions-password"),
            role="admin",
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "resource-actions@example.com",
            "password": "resource-actions-password",
        },
    )
    assert response.status_code == 200, response.text


def _configure_local_epub_cover(
    db_session,
    test_settings,
    *,
    resource_id: str,
) -> bytes:
    library = db_session.get(Library, "test-library")
    resource = db_session.get(LibraryReadableResource, resource_id)
    assert library is not None and resource is not None
    node = db_session.get(LibrarySourceNode, resource.source_node_id)
    assert node is not None
    root = test_settings.resolved_library_root
    root.mkdir(parents=True, exist_ok=True)
    relative_path = f"{resource.book_id}/{resource_id}.epub"
    source = root / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"local publication")
    cover = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    (source.parent / "cover.png").write_bytes(cover)
    source.with_suffix(".opf").write_text(
        """<package xmlns="http://www.idpf.org/2007/opf"
 xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
 <metadata><dc:title>本地标题</dc:title></metadata>
 <manifest><item id="cover" href="cover.png" media-type="image/png"
 properties="cover-image"/></manifest>
</package>""",
        encoding="utf-8",
    )
    library.root_path = str(root)
    node.relative_path = relative_path
    node.path_key = _path_key(relative_path)
    node.name = source.name
    resource.adapter_id = "epub"
    resource.format = "EPUB"
    db_session.commit()
    return cover


def test_resource_metadata_update_uses_resource_identity(client, db_session) -> None:
    _login(client, db_session)
    _add_graph(db_session, "metadata-book", "metadata-resource")
    db_session.commit()

    response = client.patch(
        "/api/books/metadata-book/resources/metadata-resource",
        json={
            "title": "Volume title",
            "resourceIndex": 2.5,
            "description": "Volume description",
            "publisher": "New Publisher",
            "language": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    metadata = db_session.get(LibraryReadableResourceMetadata, "metadata-resource")
    assert metadata is not None
    assert (
        metadata.title,
        metadata.resource_index,
        metadata.description,
        metadata.publisher,
        metadata.language,
    ) == (
        "Volume title",
        2.5,
        "Volume description",
        "New Publisher",
        "zh-CN",
    )
    assert response.json()["data"]["resource"]["id"] == "metadata-resource"


def test_book_update_uses_book_mutation_transaction(client, db_session) -> None:
    _login(client, db_session)
    _add_graph(db_session, "update-book", "update-resource")
    db_session.commit()

    response = client.patch(
        "/api/books/update-book",
        json={"title": "Updated book title", "seriesName": "A series"},
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    metadata = db_session.get(LibraryBookMetadata, "update-book")
    assert metadata is not None
    assert (metadata.title, metadata.series_name) == (
        "Updated book title",
        "A series",
    )


def test_resource_cover_regeneration_reparses_local_metadata_without_import_task(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "cover-book", "cover-resource")
    metadata = db_session.get(LibraryReadableResourceMetadata, "cover-resource")
    assert metadata is not None
    metadata.cover_path = "/covers/old.jpg"
    metadata.cover_status = "READY"
    db_session.commit()
    expected_cover = _configure_local_epub_cover(
        db_session,
        test_settings,
        resource_id="cover-resource",
    )
    before_tasks = tuple(db_session.scalars(select(LibraryImportTask.id)))
    before_asset = db_session.get(LibraryResourceAsset, "cover-resource-asset")
    assert before_asset is not None
    before_asset_state = (
        before_asset.id,
        before_asset.resource_id,
        before_asset.source_node_id,
        before_asset.import_state,
    )

    response = client.post(
        "/api/books/cover-book/resources/cover-resource/cover/regenerate"
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "targetType": "RESOURCE",
        "targetId": "cover-resource",
        "updatedResourceIds": ["cover-resource"],
        "skipped": [],
        "sourceNodeUpdated": False,
        "bookUpdated": False,
    }
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, "cover-resource")
    assert metadata is not None
    assert metadata.cover_path is not None
    assert metadata.cover_status == "READY"
    assert (test_settings.resolved_storage_root / metadata.cover_path).read_bytes() == (
        expected_cover
    )
    resource = db_session.get(LibraryReadableResource, "cover-resource")
    asset = db_session.get(LibraryResourceAsset, "cover-resource-asset")
    assert resource is not None and resource.import_state == "READY"
    assert asset is not None
    assert (
        asset.id,
        asset.resource_id,
        asset.source_node_id,
        asset.import_state,
    ) == before_asset_state
    assert tuple(db_session.scalars(select(LibraryImportTask.id))) == before_tasks


def test_resource_cover_regeneration_failure_preserves_existing_cover(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "missing-cover-book", "missing-cover-resource")
    metadata = db_session.get(
        LibraryReadableResourceMetadata,
        "missing-cover-resource",
    )
    assert metadata is not None
    metadata.cover_path = "covers/resources/existing.png"
    metadata.cover_status = "READY"
    existing = test_settings.resolved_storage_root / metadata.cover_path
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"existing")
    db_session.commit()

    response = client.post(
        "/api/books/missing-cover-book/resources/missing-cover-resource/cover/regenerate"
    )

    assert response.status_code == 422, response.text
    db_session.expire_all()
    metadata = db_session.get(
        LibraryReadableResourceMetadata,
        "missing-cover-resource",
    )
    assert metadata is not None
    assert (metadata.cover_path, metadata.cover_status) == (
        "covers/resources/existing.png",
        "READY",
    )
    assert existing.read_bytes() == b"existing"


def test_source_node_cover_regeneration_updates_resource_node_and_root_book(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "source-cover-book", "source-cover-resource")
    expected_cover = _configure_local_epub_cover(
        db_session,
        test_settings,
        resource_id="source-cover-resource",
    )

    response = client.post(
        "/api/books/source-cover-book/source-nodes/source-cover-book-node/cover/regenerate"
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["updatedResourceIds"] == ["source-cover-resource"]
    assert payload["sourceNodeUpdated"] is True
    assert payload["bookUpdated"] is True
    db_session.expire_all()
    resource_metadata = db_session.get(
        LibraryReadableResourceMetadata,
        "source-cover-resource",
    )
    source_metadata = db_session.get(
        LibrarySourceNodeMetadata,
        "source-cover-book-node",
    )
    book_metadata = db_session.get(LibraryBookMetadata, "source-cover-book")
    assert resource_metadata is not None
    assert source_metadata is not None
    assert book_metadata is not None
    assert source_metadata.cover_path == book_metadata.cover_path
    assert source_metadata.cover_status == book_metadata.cover_status == "READY"
    assert resource_metadata.cover_path is not None
    assert (
        test_settings.resolved_storage_root / resource_metadata.cover_path
    ).read_bytes() == expected_cover
    assert (
        test_settings.resolved_storage_root / source_metadata.cover_path
    ).read_bytes() == expected_cover


def test_resource_cover_upload_publishes_validated_resource_cover(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "upload-cover-book", "upload-cover-resource")
    db_session.commit()
    png = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    response = client.put(
        "/api/books/upload-cover-book/resources/upload-cover-resource/cover",
        files={"cover": ("cover.png", png, "image/png")},
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, "upload-cover-resource")
    assert metadata is not None
    assert metadata.cover_path == "covers/resources/upload-cover-resource.png"
    assert metadata.cover_status == "READY"
    assert (
        test_settings.resolved_storage_root / metadata.cover_path
    ).read_bytes() == png
    assert response.json()["data"]["resource"]["id"] == "upload-cover-resource"


def test_resource_cover_upload_rejects_invalid_content_without_changing_cover(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "invalid-cover-book", "invalid-cover-resource")
    metadata = db_session.get(LibraryReadableResourceMetadata, "invalid-cover-resource")
    assert metadata is not None
    metadata.cover_path = "covers/resources/existing.png"
    metadata.cover_status = "READY"
    existing = test_settings.resolved_storage_root / metadata.cover_path
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"existing-cover")
    db_session.commit()

    response = client.put(
        "/api/books/invalid-cover-book/resources/invalid-cover-resource/cover",
        files={"cover": ("cover.txt", b"not-an-image", "text/plain")},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_RESOURCE_COVER"
    db_session.expire_all()
    metadata = db_session.get(LibraryReadableResourceMetadata, "invalid-cover-resource")
    assert metadata is not None
    assert (metadata.cover_path, metadata.cover_status) == (
        "covers/resources/existing.png",
        "READY",
    )
    assert existing.read_bytes() == b"existing-cover"


def test_resource_asset_delete_marks_resource_failed_when_last_asset_is_removed(
    client, db_session
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "delete-book", "delete-resource")
    db_session.commit()

    response = client.delete("/api/assets/delete-resource-asset")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "assetId": "delete-resource-asset",
        "deleted": True,
    }
    resource = db_session.get(LibraryReadableResource, "delete-resource")
    assert resource is not None
    assert resource.import_state == "FAILED"
    assert db_session.get(LibraryResourceAsset, "delete-resource-asset") is None


def test_resource_actions_use_canonical_routes_and_do_not_restore_legacy_paths(
    client, db_session
) -> None:
    _login(client, db_session)
    _add_graph(db_session, "route-book", "route-resource")
    db_session.commit()

    assert (
        client.patch(
            "/api/works/route-book/versions/route-resource", json={}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/books/route-book/resources/route-resource/cover/regenerate"
        ).status_code
        == 422
    )
    assert (
        client.post("/api/books/route-book/resources/route-resource/rescan").status_code
        == 404
    )
