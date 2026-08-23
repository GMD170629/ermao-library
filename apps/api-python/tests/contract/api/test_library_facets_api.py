"""Contract tests for canonical LibraryFacet governance."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryOperation,
    LibrarySourceNode,
)
from app.models.auth import User

PASSWORD = "FacetContract123!"


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _login(client, db_session, *, role: str = "admin") -> User:
    user = User(
        id=f"facet-{role}",
        email=f"facet-{role}@example.com",
        name=f"Facet {role}",
        password_hash=hash_password(PASSWORD),
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return user


def _add_book(
    db_session,
    *,
    book_id: str,
    author: str,
    series_name: str | None = None,
    series_index: float | None = None,
) -> None:
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
            title=book_id,
            normalized_title=book_id,
            author=author,
            normalized_author=author.casefold(),
            series_name=series_name,
            series_index=series_index,
        )
    )


def _add_facet(
    db_session,
    *,
    facet_id: str,
    kind: str,
    name: str,
    book_ids: tuple[str, ...],
) -> None:
    db_session.add(
        LibraryFacet(
            id=facet_id,
            kind=kind,
            name=name,
            normalized_name=name.casefold(),
            aliases="[]",
        )
    )
    db_session.flush()
    for order, book_id in enumerate(book_ids):
        db_session.add(
            LibraryBookFacet(
                facet_id=facet_id,
                book_id=book_id,
                sort_order=order,
            )
        )


def _seed_governance_fixture(db_session) -> None:
    _add_book(
        db_session,
        book_id="facet-book-1",
        author="旧作者、共同作者",
        series_name="旧丛书",
        series_index=2,
    )
    _add_book(db_session, book_id="facet-book-2", author="共同作者")
    db_session.flush()
    _add_facet(
        db_session,
        facet_id="author-old",
        kind="AUTHOR",
        name="旧作者",
        book_ids=("facet-book-1",),
    )
    _add_facet(
        db_session,
        facet_id="author-shared",
        kind="AUTHOR",
        name="共同作者",
        book_ids=("facet-book-1", "facet-book-2"),
    )
    _add_facet(
        db_session,
        facet_id="tag-target",
        kind="TAG",
        name="科幻",
        book_ids=("facet-book-1",),
    )
    _add_facet(
        db_session,
        facet_id="tag-source",
        kind="TAG",
        name="Science Fiction",
        book_ids=("facet-book-2",),
    )
    _add_facet(
        db_session,
        facet_id="series-old",
        kind="SERIES",
        name="旧丛书",
        book_ids=("facet-book-1",),
    )
    db_session.commit()


def test_facet_page_is_authorized_paginated_and_uses_canonical_name(
    client, db_session
) -> None:
    _login(client, db_session)
    _seed_governance_fixture(db_session)

    response = client.get(
        "/api/library/facets",
        params={"kind": "AUTHOR", "page": 1, "pageSize": 20},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 2
    assert payload["totalPages"] == 1
    assert {(item["name"], item["bookCount"]) for item in payload["facets"]} == {
        ("旧作者", 1),
        ("共同作者", 2),
    }
    assert client.get("/api/library/categories").status_code == 404


def test_groupings_expose_canonical_series_facets_and_representative_books(
    client, db_session
) -> None:
    _login(client, db_session)
    _seed_governance_fixture(db_session)

    response = client.get(
        "/api/library/groupings",
        params={"kind": "SERIES", "page": 1, "pageSize": 48},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["groups"][0]["id"] == "series-old"
    assert payload["groups"][0]["name"] == "旧丛书"
    assert payload["groups"][0]["bookCount"] == 1
    assert payload["groups"][0]["representativeBooks"][0]["id"] == "facet-book-1"
    assert payload["groups"][0]["representativeBooks"][0]["coverUrl"].startswith(
        "/api/books/facet-book-1/cover"
    )
    assert client.get("/api/series").status_code == 404

    schema = client.get("/api/library/filter-schema")
    assert schema.status_code == 200, schema.text
    author_field = next(
        field for field in schema.json()["data"]["fields"] if field["key"] == "author"
    )
    assert author_field["optionSource"] == "authors"

    metadata = db_session.get(LibraryBookMetadata, "facet-book-2")
    assert metadata is not None
    metadata.author = "只存在于漂移投影"
    db_session.commit()
    options = client.get(
        "/api/library/filter-options",
        params={"source": "authors", "query": "漂移", "limit": 20},
    )
    assert options.status_code == 200, options.text
    assert options.json()["data"]["options"] == []


def test_facet_rename_updates_book_projection_aliases_and_operation(
    client, db_session
) -> None:
    user = _login(client, db_session)
    _seed_governance_fixture(db_session)

    response = client.patch(
        "/api/library/facets/author-old",
        json={"name": "新作者"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["facetId"] == "author-old"
    assert payload["operation"]["action"] == "RENAME_FACET"
    metadata = db_session.get(LibraryBookMetadata, "facet-book-1")
    facet = db_session.get(LibraryFacet, "author-old")
    assert metadata is not None and metadata.author == "新作者、共同作者"
    assert facet is not None and facet.name == "新作者"
    assert facet.aliases == '["旧作者"]'
    operation = db_session.get(LibraryOperation, payload["operation"]["id"])
    assert operation is not None and operation.user_id == user.id

    undone = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    metadata = db_session.get(LibraryBookMetadata, "facet-book-1")
    facet = db_session.get(LibraryFacet, "author-old")
    assert metadata is not None and metadata.author == "旧作者、共同作者"
    assert facet is not None and facet.name == "旧作者"
    assert facet.aliases == "[]"


def test_facet_merge_preserves_all_tag_links_and_records_operation(
    client, db_session
) -> None:
    _login(client, db_session)
    _seed_governance_fixture(db_session)

    response = client.post(
        "/api/library/facets/merge",
        json={
            "kind": "TAG",
            "targetId": "tag-target",
            "sourceIds": ["tag-source"],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["mergedIds"] == ["tag-source"]
    assert payload["operation"]["action"] == "MERGE_FACETS"
    assert db_session.get(LibraryFacet, "tag-source") is None
    target = db_session.get(LibraryFacet, "tag-target")
    assert target is not None and target.aliases == '["Science Fiction"]'
    linked_books = set(
        db_session.scalars(
            select(LibraryBookFacet.book_id).where(
                LibraryBookFacet.facet_id == "tag-target"
            )
        ).all()
    )
    assert linked_books == {"facet-book-1", "facet-book-2"}

    undone = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    assert db_session.get(LibraryFacet, "tag-source") is not None
    target = db_session.get(LibraryFacet, "tag-target")
    assert target is not None and target.aliases == "[]"
    target_books = set(
        db_session.scalars(
            select(LibraryBookFacet.book_id).where(
                LibraryBookFacet.facet_id == "tag-target"
            )
        ).all()
    )
    source_books = set(
        db_session.scalars(
            select(LibraryBookFacet.book_id).where(
                LibraryBookFacet.facet_id == "tag-source"
            )
        ).all()
    )
    assert target_books == {"facet-book-1"}
    assert source_books == {"facet-book-2"}


def test_deleting_series_clears_series_projection_and_index(client, db_session) -> None:
    _login(client, db_session)
    _seed_governance_fixture(db_session)

    response = client.delete("/api/library/facets/series-old")

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["deleted"] is True
    metadata = db_session.get(LibraryBookMetadata, "facet-book-1")
    assert metadata is not None
    assert metadata.series_name is None
    assert metadata.series_index is None
    assert db_session.get(LibraryFacet, "series-old") is None

    undone = client.post(f"/api/library/operations/{payload['operation']['id']}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    metadata = db_session.get(LibraryBookMetadata, "facet-book-1")
    assert metadata is not None
    assert metadata.series_name == "旧丛书"
    assert metadata.series_index == 2
    assert db_session.get(LibraryFacet, "series-old") is not None


def test_facet_mutations_require_system_manager(client, db_session) -> None:
    _login(client, db_session, role="member")

    groupings = client.get(
        "/api/library/groupings",
        params={"kind": "AUTHOR", "page": 1, "pageSize": 48},
    )
    assert groupings.status_code == 200

    response = client.patch("/api/library/facets/missing", json={"name": "new"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"
