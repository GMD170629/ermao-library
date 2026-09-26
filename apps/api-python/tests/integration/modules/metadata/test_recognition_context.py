"""SQLite checks for bounded and target-owned recognition projections."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
)
from app.modules.metadata.application.recognition import assess_candidates
from app.modules.metadata.public import load_recognition_context, provider_context


def _node(node_id: str, path: str, *, directory: bool) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 100,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _book(db: Session, book_id: str) -> None:
    root = _node(f"{book_id}-root", book_id, directory=True)
    db.add(root)
    db.flush()
    db.add_all(
        [
            LibraryBook(
                id=book_id, library_id="test-library", source_node_id=root.id
            ),
            LibraryBookMetadata(
                book_id=book_id,
                title=f"{book_id} title",
                normalized_title=f"{book_id} title",
                author="Book Author",
                protected_fields='["author"]',
            ),
        ]
    )
    db.flush()


def _resource(db: Session, book_id: str, index: int, *, isbn: str) -> str:
    resource_id = f"{book_id}-resource-{index:02d}"
    node = _node(
        f"{resource_id}-node", f"{book_id}/volume-{index:02d}.epub",
        directory=False,
    )
    db.add(node)
    db.flush()
    db.add_all(
        [
            LibraryReadableResource(
                id=resource_id,
                library_id="test-library",
                book_id=book_id,
                source_node_id=node.id,
                adapter_id="epub-file",
                adapter_version="1",
                format="EPUB",
                import_state="READY",
            ),
            LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title=f"Volume {index}",
                isbn=isbn,
                protected_fields='["isbn"]' if index == 1 else "[]",
            ),
        ]
    )
    db.flush()
    return resource_id


def test_resource_projection_is_owned_and_does_not_leak_to_parent(
    db_session: Session,
) -> None:
    _book(db_session, "target-book")
    first_id = _resource(db_session, "target-book", 1, isbn="9780306406157")
    second_id = _resource(db_session, "target-book", 2, isbn="9791090636071")
    _book(db_session, "other-book")
    foreign_id = _resource(db_session, "other-book", 1, isbn="9780000000002")
    db_session.commit()

    first = load_recognition_context(
        db_session, book_id="target-book", resource_id=first_id
    )
    second = load_recognition_context(
        db_session, book_id="target-book", resource_id=second_id
    )
    parent = load_recognition_context(db_session, book_id="target-book")
    assert first is not None and second is not None and parent is not None
    assert first.identity.isbn == "9780306406157"
    assert second.identity.isbn == "9791090636071"
    assert parent.identity.isbn is None
    assert first.protected == frozenset({"isbn"})
    assert second.protected == frozenset()
    assert parent.protected == frozenset({"author"})
    assert first.revision != second.revision
    assert first.related_revision == second.related_revision
    assert first.related_revision
    assert provider_context(db_session, first)["resources"] == [
        {"format": "EPUB", "hidden": False}
    ]
    assert load_recognition_context(
        db_session, book_id="target-book", resource_id=foreign_id
    ) is None

    first_metadata = db_session.get(LibraryReadableResourceMetadata, first_id)
    assert first_metadata is not None
    first_metadata.isbn = "9780000000002"
    db_session.commit()
    changed_first = load_recognition_context(
        db_session, book_id="target-book", resource_id=first_id
    )
    unchanged_second = load_recognition_context(
        db_session, book_id="target-book", resource_id=second_id
    )
    unchanged_parent = load_recognition_context(db_session, book_id="target-book")
    assert changed_first is not None
    assert unchanged_second is not None
    assert unchanged_parent is not None
    assert changed_first.revision != first.revision
    assert unchanged_second.revision == second.revision
    assert unchanged_parent.revision == parent.revision


def test_provider_projection_and_sql_count_stay_bounded_as_library_grows(
    db_session: Session,
) -> None:
    _book(db_session, "target-book")
    for index in range(1, 13):
        _resource(db_session, "target-book", index, isbn="9780306406157")
    db_session.commit()

    def project() -> tuple[int, int]:
        db_session.expunge_all()
        count = 0

        def count_select(
            connection: Connection,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            nonlocal count
            if statement.lstrip().upper().startswith("SELECT"):
                count += 1

        bind = db_session.get_bind()
        event.listen(bind, "before_cursor_execute", count_select)
        try:
            context = load_recognition_context(db_session, book_id="target-book")
            assert context is not None
            data = provider_context(db_session, context)
        finally:
            event.remove(bind, "before_cursor_execute", count_select)
        resources = data["resources"]
        assert isinstance(resources, list)
        return count, len(resources)

    before_queries, before_resources = project()
    assert before_resources == 8
    for index in range(10):
        other_id = f"unrelated-book-{index:02d}"
        _book(db_session, other_id)
        _resource(db_session, other_id, 1, isbn="9780306406157")
    db_session.commit()
    after_queries, after_resources = project()
    assert after_resources == 8
    assert before_queries == after_queries


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("remote_index", [1, 2])
def test_confirmed_parent_and_resource_volume_reach_shared_matcher(db_session, confirmed, remote_index):
    _book(db_session, "work")
    resource_id = _resource(db_session, "work", 1, isbn="0306406152")
    parent = db_session.get(LibraryBookMetadata, "work")
    parent.title = "示例书"
    parent.protected_fields = '["title", "author"]' if confirmed else "[]"
    parent.series_index = 99
    resource = db_session.get(LibraryReadableResourceMetadata, resource_id)
    resource.title = "第一卷"
    resource.resource_index = 1
    resource.protected_fields = '["resource_index"]'
    db_session.commit()
    projected = load_recognition_context(db_session, book_id="work", resource_id=resource_id)
    assert projected is not None
    _, decision = assess_candidates(projected, "douban", [{
        "id": "one", "title": "示例书", "author": "Book Author",
        "matchLevel": "VOLUME", "resourceIndex": remote_index,
        "isbn": "9780306406157", "isbnScope": "EDITION",
    }])[0]
    assert projected.identity.isbn_scope == "UNKNOWN"
    assert decision.outcome == ("REJECTED" if remote_index == 2 else "MATCHED" if confirmed else "AMBIGUOUS")
    assert "resource.isbn" not in decision.allowed_fields
    assert db_session.get(LibraryReadableResourceMetadata, resource_id).title == "第一卷"


def test_unconfirmed_resource_order_does_not_supply_publication_volume(db_session):
    _book(db_session, "work")
    resource_id = _resource(db_session, "work", 1, isbn="0306406152")
    resource = db_session.get(LibraryReadableResourceMetadata, resource_id)
    resource.title = "示例书 第1卷"
    resource.resource_index = 99
    db_session.commit()
    projected = load_recognition_context(db_session, book_id="work", resource_id=resource_id)
    _, decision = assess_candidates(projected, "douban", [{
        "id": "one", "title": "示例书 第1卷", "author": "Book Author",
        "resourceIndex": 88, "seriesIndex": 77,
    }])[0]
    assert decision.outcome == "MATCHED"
    assert decision.level == "VOLUME"


def test_confirmed_resource_volume_cannot_hide_its_own_title_conflict(db_session):
    _book(db_session, "work")
    resource_id = _resource(db_session, "work", 1, isbn="0306406152")
    resource = db_session.get(LibraryReadableResourceMetadata, resource_id)
    resource.title = "示例书 第1卷"
    resource.resource_index = 2
    resource.protected_fields = '["resource_index", "isbn"]'
    db_session.commit()
    projected = load_recognition_context(db_session, book_id="work", resource_id=resource_id)
    _, decision = assess_candidates(projected, "douban", [{
        "id": "one", "title": "示例书 第2卷", "author": "Book Author",
        "isbn": "9780306406157", "isbnScope": "EDITION",
    }])[0]
    assert decision.outcome == "REJECTED"
    assert "target:title_volume" in decision.evidence_ids
    assert "target:resource_index" in decision.evidence_ids
    assert not decision.allowed_fields


def test_persisted_isbn_alone_does_not_confirm_an_edition(db_session):
    _book(db_session, "work")
    resource_id = _resource(db_session, "work", 1, isbn="0306406152")
    resource = db_session.get(LibraryReadableResourceMetadata, resource_id)
    resource.title = "示例书"
    db_session.commit()
    projected = load_recognition_context(db_session, book_id="work", resource_id=resource_id)
    _, decision = assess_candidates(projected, "douban", [{
        "id": "one", "title": "示例书", "isbn": "9780306406157", "isbnScope": "EDITION",
    }])[0]
    assert projected.identity.isbn_scope == "UNKNOWN"
    assert decision.outcome == "AMBIGUOUS"
    assert not decision.allowed_fields
