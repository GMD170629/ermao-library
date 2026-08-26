from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
)
from app.models.auth import User

PASSWORD = "RecognizedMetadata123!"


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _login(client, db: Session, *, role: str) -> None:
    user = User(
        id=f"metadata-{role}",
        email=f"metadata-{role}@example.com",
        name=f"Metadata {role}",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def _add_book(db: Session, *, book_id: str) -> str:
    root_id = f"{book_id}-root"
    root_path = f"{book_id}/"
    root = LibrarySourceNode(
        id=root_id,
        library_id="test-library",
        relative_path=root_path,
        path_key=_path_key(root_path),
        name=book_id,
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    db.add(root)
    db.flush()
    db.add(
        LibraryBook(
            id=book_id,
            library_id="test-library",
            source_node_id=root_id,
        )
    )
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=f"{book_id} title",
            normalized_title=f"{book_id} title",
            author="旧作者",
        )
    )
    resource_id = f"{book_id}-resource"
    resource_path = f"{book_id}/volume.epub"
    source = LibrarySourceNode(
        id=f"{resource_id}-node",
        library_id="test-library",
        relative_path=resource_path,
        path_key=_path_key(resource_path),
        name="volume.epub",
        physical_kind="REGULAR_FILE",
        observed_size_bytes=100,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    db.add(source)
    db.flush()
    db.add(
        LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=source.id,
            adapter_id="epub-file",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
    )
    db.flush()
    db.add(
        LibraryReadableResourceMetadata(
            resource_id=resource_id,
            title="第一卷",
            resource_index=1,
        )
    )
    db.commit()
    return resource_id


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "id": "subject-1",
        "source": "douban",
        "title": "候选标题",
        "author": "候选作者",
        "description": "候选简介",
        "tags": ["漫画", " 科幻 ", "漫画"],
        "seriesName": "候选系列",
        "seriesIndex": 2,
        "publisher": "候选出版社",
        "publishedAt": "2026-08-26T00:00:00Z",
        "language": "zh-CN",
        "isbn": "9780000000001",
        "identifier": "subject:1",
        "narrator": "朗读者",
        "abridged": False,
        "resourceIndex": 2,
        "coverUrl": None,
        "confidence": 0.9,
    }
    candidate.update(overrides)
    return candidate


def test_metadata_apply_requires_authentication(client) -> None:
    response = client.post(
        "/api/books/missing/metadata/apply",
        json={
            "scope": "book",
            "resourceId": None,
            "candidate": _candidate(),
            "fields": ["book.author"],
        },
    )

    assert response.status_code == 401


def test_metadata_apply_requires_system_manager(client, db_session: Session) -> None:
    _login(client, db_session, role="member")
    response = client.post(
        "/api/books/missing/metadata/apply",
        json={
            "scope": "book",
            "resourceId": None,
            "candidate": _candidate(),
            "fields": ["book.author"],
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"


def test_resource_apply_updates_selected_book_resource_and_tag_fields(
    client, db_session: Session
) -> None:
    _login(client, db_session, role="admin")
    resource_id = _add_book(db_session, book_id="recognized-book")

    response = client.post(
        "/api/books/recognized-book/metadata/apply",
        json={
            "scope": "resource",
            "resourceId": resource_id,
            "candidate": _candidate(),
            "fields": [
                "book.author",
                "book.tags",
                "resource.publisher",
                "resource.abridged",
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "appliedFields": [
            "book.author",
            "book.tags",
            "resource.publisher",
            "resource.abridged",
        ],
        "skippedFields": [],
        "coverStatus": "notSelected",
    }
    db_session.expire_all()
    book_metadata = db_session.get(LibraryBookMetadata, "recognized-book")
    resource_metadata = db_session.get(LibraryReadableResourceMetadata, resource_id)
    assert book_metadata is not None
    assert resource_metadata is not None
    assert book_metadata.author == "候选作者"
    assert resource_metadata.publisher == "候选出版社"
    assert resource_metadata.abridged is False
    tags = db_session.scalars(
        select(LibraryFacet.name)
        .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
        .where(
            LibraryBookFacet.book_id == "recognized-book",
            LibraryFacet.kind == "TAG",
        )
        .order_by(LibraryBookFacet.sort_order)
    ).all()
    assert tags == ["漫画", "科幻"]


def test_resource_apply_hides_cross_book_targets(client, db_session: Session) -> None:
    _login(client, db_session, role="admin")
    _add_book(db_session, book_id="book-one")
    other_resource_id = _add_book(db_session, book_id="book-two")

    response = client.post(
        "/api/books/book-one/metadata/apply",
        json={
            "scope": "resource",
            "resourceId": other_resource_id,
            "candidate": _candidate(),
            "fields": ["resource.publisher"],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "METADATA_TARGET_NOT_FOUND"


def test_metadata_apply_rejects_repeated_or_unavailable_fields(
    client, db_session: Session
) -> None:
    _login(client, db_session, role="admin")
    _add_book(db_session, book_id="invalid-book")

    repeated = client.post(
        "/api/books/invalid-book/metadata/apply",
        json={
            "scope": "book",
            "resourceId": None,
            "candidate": _candidate(),
            "fields": ["book.author", "book.author"],
        },
    )
    unavailable = client.post(
        "/api/books/invalid-book/metadata/apply",
        json={
            "scope": "book",
            "resourceId": None,
            "candidate": _candidate(author=None),
            "fields": ["book.author"],
        },
    )

    assert repeated.status_code == 422
    assert repeated.json()["error"]["code"] == "INVALID_METADATA_APPLY"
    assert unavailable.status_code == 422
    assert unavailable.json()["error"]["code"] == "INVALID_METADATA_APPLY"
