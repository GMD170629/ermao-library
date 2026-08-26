"""Contract tests for canonical auditable multi-Book operations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryOperation,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
    ReaderResourceProgress,
)
from app.models.auth import User, UserLibraryAccess
from app.models.shelf import Shelf, ShelfBook

PASSWORD = "BulkContract123!"


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _login(client, db_session, *, role: str = "admin") -> User:
    user = User(
        id=f"bulk-{role}",
        email=f"bulk-{role}@example.com",
        name=f"Bulk {role}",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    db_session.add(user)
    db_session.flush()
    if role != "admin":
        db_session.add(UserLibraryAccess(user_id=user.id, library_id="test-library"))
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return user


def _add_book(db_session, *, index: int) -> None:
    book_id = f"bulk-book-{index}"
    relative_path = f"{book_id}.epub"
    node = LibrarySourceNode(
        id=f"{book_id}-node",
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=100,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    db_session.add(node)
    db_session.flush()
    db_session.add(
        LibraryBook(
            id=book_id,
            library_id="test-library",
            source_node_id=node.id,
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=f"旧书名 {index}",
            normalized_title=f"旧书名{index}",
            author="旧作者",
            normalized_author="旧作者",
        )
    )
    db_session.flush()
    resource_id = f"bulk-resource-{index}"
    db_session.add(
        LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=node.id,
            adapter_id="epub-file",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(
            resource_id=resource_id,
            title=f"第 {index} 卷",
            resource_index=index,
        )
    )


def _seed_books(db_session) -> tuple[str, str]:
    _add_book(db_session, index=1)
    _add_book(db_session, index=2)
    db_session.flush()
    tag = LibraryFacet(
        id="bulk-tag-old",
        kind="TAG",
        name="临时",
        normalized_name="临时",
        aliases="[]",
    )
    db_session.add(tag)
    db_session.flush()
    db_session.add_all(
        [
            LibraryBookFacet(
                facet_id=tag.id,
                book_id="bulk-book-1",
                sort_order=0,
            ),
            LibraryBookFacet(
                facet_id=tag.id,
                book_id="bulk-book-2",
                sort_order=0,
            ),
        ]
    )
    db_session.commit()
    return "bulk-book-1", "bulk-book-2"


def _png_cover() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 120), color=(202, 92, 48)).save(output, format="PNG")
    return output.getvalue()


def test_bulk_metadata_updates_facets_and_writes_library_operation(
    client, db_session
) -> None:
    user = _login(client, db_session)
    book_ids = _seed_books(db_session)

    response = client.post(
        "/api/library/operations/books/metadata",
        json={
            "ids": list(book_ids),
            "fields": {"author": "新作者", "seriesName": "新丛书"},
            "addTags": ["科幻"],
            "removeTags": ["临时"],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["updated"] == 2
    assert payload["operation"]["action"] == "BULK_UPDATE_METADATA"
    refreshed = client.get(f"/api/books/{book_ids[0]}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["data"]["book"]["tags"] == ["科幻"]
    operation = db_session.get(LibraryOperation, payload["operation"]["id"])
    assert operation is not None and operation.user_id == user.id
    for book_id in book_ids:
        metadata = db_session.get(LibraryBookMetadata, book_id)
        assert metadata is not None
        assert metadata.author == "新作者"
        assert metadata.series_name == "新丛书"
        facets = set(
            db_session.scalars(
                select(LibraryFacet.name)
                .join(
                    LibraryBookFacet,
                    LibraryBookFacet.facet_id == LibraryFacet.id,
                )
                .where(LibraryBookFacet.book_id == book_id)
            ).all()
        )
        assert facets == {"新作者", "新丛书", "科幻"}

    undone = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["data"]["operation"]["status"] == "UNDONE"
    db_session.expire_all()
    for book_id in book_ids:
        metadata = db_session.get(LibraryBookMetadata, book_id)
        assert metadata is not None
        assert metadata.author == "旧作者"
        assert metadata.series_name is None
        facets = set(
            db_session.scalars(
                select(LibraryFacet.name)
                .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
                .where(LibraryBookFacet.book_id == book_id)
            ).all()
        )
        assert facets == {"临时"}
    restored = client.get(f"/api/books/{book_ids[0]}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["book"]["tags"] == ["临时"]
    repeated = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert repeated.status_code == 409


def test_bulk_find_replace_previews_and_updates_resource_titles(
    client, db_session
) -> None:
    _login(client, db_session)
    book_ids = _seed_books(db_session)
    request = {
        "ids": list(book_ids),
        "field": "resourceTitle",
        "find": "卷",
        "replacement": "册",
        "regex": False,
        "caseSensitive": False,
        "startNumber": 1,
    }

    preview = client.post(
        "/api/library/operations/books/find-replace-preview",
        json=request,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["changedBooks"] == 2
    assert preview.json()["data"]["changedValues"] == 2

    applied = client.post(
        "/api/library/operations/books/find-replace",
        json=request,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["changedValues"] == 2
    assert (
        db_session.get(LibraryReadableResourceMetadata, "bulk-resource-1").title
        == "第 1 册"
    )
    assert (
        db_session.get(LibraryReadableResourceMetadata, "bulk-resource-2").title
        == "第 2 册"
    )

    undone = client.post(
        f"/api/library/operations/{applied.json()['data']['operation']['id']}/undo"
    )
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    assert (
        db_session.get(LibraryReadableResourceMetadata, "bulk-resource-1").title
        == "第 1 卷"
    )
    assert (
        db_session.get(LibraryReadableResourceMetadata, "bulk-resource-2").title
        == "第 2 卷"
    )


def test_personal_bulk_shelf_and_reading_status_are_not_manager_only(
    client, db_session
) -> None:
    user = _login(client, db_session, role="member")
    book_ids = _seed_books(db_session)
    db_session.add(
        Shelf(
            id="bulk-shelf",
            owner_user_id=user.id,
            name="待读",
            kind="STATIC",
            rules_json="{}",
        )
    )
    db_session.commit()

    shelf_response = client.post(
        "/api/library/operations/books/shelf-membership",
        json={
            "ids": list(book_ids),
            "shelfId": "bulk-shelf",
            "membership": "ADD",
        },
    )
    assert shelf_response.status_code == 200, shelf_response.text
    assert shelf_response.json()["data"]["updated"] == 2
    assert set(
        db_session.scalars(
            select(ShelfBook.book_id).where(ShelfBook.shelf_id == "bulk-shelf")
        ).all()
    ) == set(book_ids)

    reading_response = client.post(
        "/api/library/operations/books/reading-status",
        json={"ids": list(book_ids), "status": "FINISHED"},
    )
    assert reading_response.status_code == 200, reading_response.text
    assert reading_response.json()["data"]["updated"] == 2
    assert reading_response.json()["data"]["operation"]["undoAvailable"] is False
    progress = db_session.scalars(
        select(ReaderResourceProgress).where(ReaderResourceProgress.user_id == user.id)
    ).all()
    assert len(progress) == 2
    assert {row.percent for row in progress} == {100.0}

    repeated = client.post(
        "/api/library/operations/books/reading-status",
        json={"ids": list(book_ids), "status": "FINISHED"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["updated"] == 0
    assert repeated.json()["data"]["changedValues"] == 0

    recent_books = client.get("/api/dashboard/recent-books", params={"limit": 10})
    recent_reading = client.get("/api/dashboard/recent-reading", params={"limit": 10})
    continuing = client.get("/api/dashboard/continue-reading")
    assert recent_books.status_code == 200, recent_books.text
    assert recent_reading.status_code == 200, recent_reading.text
    assert continuing.status_code == 200, continuing.text
    assert {book["id"] for book in recent_books.json()["data"]["books"]} == set(
        book_ids
    )
    assert {book["id"] for book in recent_reading.json()["data"]["books"]} == set(
        book_ids
    )
    continue_item = continuing.json()["data"]["item"]
    assert continue_item["bookId"] in book_ids
    assert continue_item["resumeResourceId"].startswith("bulk-resource-")
    assert continue_item["progress"] == 100


def test_bulk_metadata_noop_is_finalized_and_reports_no_changes(
    client, db_session
) -> None:
    _login(client, db_session)
    book_ids = _seed_books(db_session)

    response = client.post(
        "/api/library/operations/books/metadata",
        json={
            "ids": list(book_ids),
            "fields": {"author": "旧作者"},
            "addTags": ["临时"],
            "removeTags": ["不存在"],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["updated"] == 0
    assert payload["changedValues"] == 0
    assert payload["operation"]["status"] == "FINALIZED"
    assert payload["operation"]["undoAvailable"] is False


def test_bulk_cover_replace_publishes_each_book_anchor_and_records_operation(
    client, db_session, test_settings
) -> None:
    _login(client, db_session)
    book_ids = _seed_books(db_session)

    response = client.post(
        "/api/library/operations/books/covers",
        data={
            "ids": f'["{book_ids[0]}","{book_ids[1]}"]',
            "action": "replace",
            "ratio": "2:3",
            "quality": "82",
            "maxDimension": "1600",
        },
        files={"cover": ("cover.png", _png_cover(), "image/png")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["updated"] == 2
    assert payload["skipped"] == []
    assert payload["operation"]["action"] == "BULK_BOOK_COVERS"
    assert payload["operation"]["undoAvailable"] is False
    for index, book_id in enumerate(book_ids, start=1):
        book_metadata = db_session.get(LibraryBookMetadata, book_id)
        source_metadata = db_session.get(
            LibrarySourceNodeMetadata, f"bulk-book-{index}-node"
        )
        assert book_metadata is not None and source_metadata is not None
        assert book_metadata.cover_path == source_metadata.cover_path
        assert book_metadata.cover_status == "READY"
        assert source_metadata.cover_path is not None
        assert (
            test_settings.resolved_storage_root / source_metadata.cover_path
        ).is_file()

    rejected_undo = client.post(
        f"/api/library/operations/{payload['operation']['id']}/undo"
    )
    assert rejected_undo.status_code == 409

    cropped = client.post(
        "/api/library/operations/books/covers",
        data={
            "ids": f'["{book_ids[0]}","{book_ids[1]}"]',
            "action": "crop",
            "ratio": "1:1",
            "quality": "82",
            "maxDimension": "1600",
        },
    )
    assert cropped.status_code == 200, cropped.text
    db_session.expire_all()
    for book_id in book_ids:
        cover_path = db_session.get(LibraryBookMetadata, book_id).cover_path
        assert cover_path is not None
        with Image.open(test_settings.resolved_storage_root / cover_path) as image:
            assert image.width == image.height

    regenerated = client.post(
        "/api/library/operations/books/covers",
        data={
            "ids": f'["{book_ids[0]}","{book_ids[1]}"]',
            "action": "regenerate",
            "ratio": "2:3",
            "quality": "82",
            "maxDimension": "1600",
        },
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["data"]["updated"] == 2
    db_session.expire_all()
    for index, book_id in enumerate(book_ids, start=1):
        book_metadata = db_session.get(LibraryBookMetadata, book_id)
        resource_metadata = db_session.get(
            LibraryReadableResourceMetadata, f"bulk-resource-{index}"
        )
        source_metadata = db_session.get(
            LibrarySourceNodeMetadata, f"bulk-book-{index}-node"
        )
        assert book_metadata is not None and book_metadata.cover_status == "PENDING"
        assert resource_metadata is not None
        assert resource_metadata.cover_path is None
        assert resource_metadata.cover_status == "PENDING"
        assert source_metadata is not None and source_metadata.cover_status == "PENDING"


def test_operation_owner_is_enforced_for_non_manager(client, db_session) -> None:
    _login(client, db_session)
    book_ids = _seed_books(db_session)
    changed = client.post(
        "/api/library/operations/books/metadata",
        json={"ids": list(book_ids), "fields": {"author": "新作者"}},
    )
    assert changed.status_code == 200, changed.text
    operation_id = changed.json()["data"]["operation"]["id"]

    client.cookies.clear()
    _login(client, db_session, role="member")
    forbidden = client.post(f"/api/library/operations/{operation_id}/undo")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "OPERATION_UNDO_FORBIDDEN"


def test_manager_metadata_action_rejects_member_and_legacy_routes_stay_absent(
    client, db_session
) -> None:
    _login(client, db_session, role="member")
    book_ids = _seed_books(db_session)

    forbidden = client.post(
        "/api/library/operations/books/metadata",
        json={"ids": list(book_ids), "fields": {"author": "新作者"}},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"

    client.cookies.clear()
    _login(client, db_session, role="admin")
    assert client.post("/api/books/bulk", json={}).status_code in {404, 405}
    assert client.post("/api/books/bulk/find-replace/preview", json={}).status_code in {
        404,
        405,
    }

    overview = client.get("/api/management/overview")
    assert overview.status_code == 200, overview.text
    overview_data = overview.json()["data"]
    assert "failedImports" in overview_data["cards"]
    assert "eventLogSizeBytes" in overview_data["cards"]
    assert "database" in overview_data["checks"]
    assert isinstance(overview_data["recentEvents"], list)
