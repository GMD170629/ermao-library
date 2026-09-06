"""Regression for per-book rescans of the actor's entire v5 progress history.

Reuse the existing library seed and VM-step instrumentation. No HTTP server,
release fixture mutation, custom query implementation, or wall-time assertions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Library,
    LibraryReadableResource,
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
)
from app.models.auth import User, UserLibraryAccess
from app.modules.library.infrastructure.book_list import list_books
from app.modules.library.public import BookListQuery
from app.modules.reader.infrastructure.v5_library_queries import (
    SqlAlchemyReaderV5LibraryPresentationQueries,
)
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort
from tests.contract.api.test_reader_v5_progress import _presentation
from tests.integration.modules.library.test_dashboard_query_scaling import (
    _seed_manual_library,
    _sqlite_vm_steps,
)


@pytest.fixture()
def recent_read_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            db.add(
                Library(
                    id="test-library",
                    name="Recent read test",
                    root_path="/recent-read-test",
                    organization_mode="FLAT",
                )
            )
            db.commit()
            yield db
    finally:
        engine.dispose()


@pytest.fixture()
def recent_read_queries(
    recent_read_session: Session,
) -> ReaderV5LibraryPresentationQueryPort:
    return SqlAlchemyReaderV5LibraryPresentationQueries(recent_read_session)


def _actor(db: Session, *, role: str = "admin", user_id: str = "recent-reader") -> User:
    user = User(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Recent reader",
        password_hash="test",
        role=role,
    )
    db.add(user)
    db.flush()
    if role == "member":
        db.add(UserLibraryAccess(user_id=user.id, library_id="test-library"))
    return user


def _progress(db: Session, *, user_id: str, index: int, when: datetime) -> None:
    db.add(
        ReaderResourceProgressV5(
            id=f"recent-progress-{user_id}-{index}",
            user_id=user_id,
            resource_id=f"scale-resource-{index:06d}",
            client_id="recent-read-test",
            mutation_id=f"00000000-0000-4000-8000-{index:012d}",
            locator_json="{}",
            presentation_json=json.dumps(
                _presentation(display_percent=40, total_progression=0.4)
            ),
            display_percent=40,
            total_progression=0.4,
            captured_at=when,
            updated_at=when,
            revision=1,
        )
    )


@pytest.mark.parametrize("search", [None, "Scale book"])
@pytest.mark.parametrize("role", ["admin", "member"])
def test_recent_read_work_does_not_multiply_books_by_progress(
    recent_read_session: Session,
    recent_read_queries: ReaderV5LibraryPresentationQueryPort,
    search: str | None,
    role: str,
) -> None:
    db = recent_read_session
    user = _actor(db, role=role)
    _seed_manual_library(db, book_count=1_000)
    reader = recent_read_queries
    query = BookListQuery(
        page=1,
        requested_page_size=5 if search else 50,
        sort="recent_read",
        projection="search" if search else "bookshelf",
        search=search,
    )
    empty, empty_steps = _sqlite_vm_steps(
        db, lambda: list_books(db, user, query, reader_queries=reader)
    )
    now = datetime(2026, 9, 6, tzinfo=UTC)
    for index in range(800):
        _progress(db, user_id=user.id, index=index, when=now + timedelta(seconds=index))
    db.commit()
    populated, populated_steps = _sqlite_vm_steps(
        db, lambda: list_books(db, user, query, reader_queries=reader)
    )
    assert empty.total == populated.total == 1_000
    assert len(populated.books) == query.requested_page_size
    assert [book["id"] for book in populated.books] == [
        f"scale-book-{index:06d}"
        for index in range(799, 799 - len(populated.books), -1)
    ]
    # Retain the neighboring owner's existing bound for 2,000 books. This case
    # has half as many books and must not perform B*P progress/resource lookups.
    print(
        f"recent_read search={search!r}: empty={empty_steps}, populated={populated_steps}"
    )
    assert populated_steps < 1_000_000, (empty_steps, populated_steps)


@pytest.mark.parametrize("role", ["admin", "member"])
def test_recent_read_preserves_resource_visibility_actor_scope_and_pagination(
    recent_read_session: Session,
    recent_read_queries: ReaderV5LibraryPresentationQueryPort,
    role: str,
) -> None:
    db = recent_read_session
    user = _actor(db, role=role)
    other = _actor(db, user_id="other-reader")
    _seed_manual_library(db, book_count=9)
    now = datetime(2026, 9, 6, tzinfo=UTC)
    for index, seconds in ((0, 10), (1, 20), (2, 20), (4, 100), (5, 100), (6, 30)):
        _progress(
            db, user_id=user.id, index=index, when=now + timedelta(seconds=seconds)
        )
    _progress(db, user_id=other.id, index=3, when=now + timedelta(seconds=200))
    resources = {
        resource.id: resource
        for resource in db.scalars(select(LibraryReadableResource))
    }
    resources["scale-resource-000004"].enablement_state = "DISABLED"
    resources["scale-resource-000005"].import_state = "FAILED"
    # A second visible resource contributes max(updated_at) to the same book.
    resources["scale-resource-000006"].book_id = "scale-book-000000"
    db.add_all(
        [
            ReaderResourceReadingStatusV5(
                id="recent-explicit-unread",
                user_id=user.id,
                resource_id="scale-resource-000001",
                status="UNREAD",
                updated_at=now + timedelta(seconds=300),
            ),
            ReaderResourceReadingStatusV5(
                id="recent-status-only",
                user_id=user.id,
                resource_id="scale-resource-000008",
                status="FINISHED",
                updated_at=now + timedelta(seconds=400),
            ),
        ]
    )
    db.commit()
    reader = recent_read_queries
    query = BookListQuery(
        page=1,
        requested_page_size=2,
        sort="recent_read",
        sort_direction="desc",
        projection="search",
    )
    first = list_books(db, user, query, reader_queries=reader)
    second = list_books(db, user, replace(query, page=2), reader_queries=reader)
    ascending = list_books(
        db,
        user,
        replace(query, requested_page_size=20, sort_direction="asc"),
        reader_queries=reader,
    )
    hit = list_books(
        db,
        user,
        replace(query, search="Scale book", requested_page_size=20),
        reader_queries=reader,
    )
    miss = list_books(
        db,
        user,
        replace(query, search="no-such-recent-read-test"),
        reader_queries=reader,
    )
    assert first.total == second.total == ascending.total == hit.total == 9
    assert [book["id"] for book in first.books] == [
        "scale-book-000000",
        "scale-book-000001",
    ]
    assert [book["id"] for book in second.books] == [
        "scale-book-000002",
        "scale-book-000003",
    ]
    assert [book["id"] for book in hit.books] == [
        f"scale-book-{index:06d}" for index in range(9)
    ]
    assert [book["id"] for book in ascending.books] == [
        f"scale-book-{index:06d}" for index in (3, 4, 5, 6, 7, 8, 1, 2, 0)
    ]
    assert miss.total == 0 and miss.books == []
    if role == "member":
        db.execute(
            delete(UserLibraryAccess).where(UserLibraryAccess.user_id == user.id)
        )
        db.commit()
        revoked = list_books(db, user, query, reader_queries=reader)
        assert revoked.total == 0 and revoked.books == []
