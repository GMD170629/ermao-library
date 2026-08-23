from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibrarySourceNode,
)
from app.models.auth import User, UserLibraryAccess
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)


def _node(
    node_id: str, path: str, library_id: str = "test-library"
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id=library_id,
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _book(
    db: Session,
    *,
    book_id: str,
    title: str,
    author: str,
    library_id: str = "test-library",
    visibility_state: str = "VISIBLE",
) -> LibraryBook:
    node = _node(f"{book_id}-node", f"{book_id}/", library_id)
    book = LibraryBook(
        library_id=library_id,
        id=book_id,
        source_node_id=node.id,
        visibility_state=visibility_state,
    )
    db.add(node)
    db.flush()
    db.add(book)
    db.flush()
    db.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=title,
            normalized_title=title.casefold(),
            author=author,
            normalized_author=author.casefold(),
        )
    )
    db.flush()
    return book


def _facet(db: Session, facet_id: str, kind: str, name: str) -> LibraryFacet:
    facet = LibraryFacet(
        id=facet_id,
        kind=kind,
        name=name,
        normalized_name=name.casefold(),
    )
    db.add(facet)
    db.flush()
    return facet


def test_groupings_filter_visibility_search_and_stable_page(
    db_session: Session,
) -> None:
    user = User(
        id="library-groupings-user",
        email="library-groupings@example.com",
        name="书库分组",
        password_hash="unused",
        role="admin",
    )
    _book(db_session, book_id="series-2", title="第二册", author="林川、周禾")
    _book(db_session, book_id="series-1", title="第一册", author="林川")
    _book(db_session, book_id="single", title="单册", author="艾青")
    _book(db_session, book_id="unknown", title="佚名", author="未知作者")
    _book(
        db_session,
        book_id="hidden",
        title="隐藏册",
        author="秘密作者",
        visibility_state="HIDDEN",
    )
    lin = _facet(db_session, "facet-author-lin", "AUTHOR", "林川")
    zhou = _facet(db_session, "facet-author-zhou", "AUTHOR", "周禾")
    ai = _facet(db_session, "facet-author-ai", "AUTHOR", "艾青")
    unknown = _facet(db_session, "facet-author-unknown", "AUTHOR", "未知作者")
    hidden = _facet(db_session, "facet-author-hidden", "AUTHOR", "秘密作者")
    db_session.add_all(
        [
            user,
            LibraryBookFacet(facet_id=lin.id, book_id="series-1"),
            LibraryBookFacet(facet_id=lin.id, book_id="series-2"),
            LibraryBookFacet(facet_id=zhou.id, book_id="series-2"),
            LibraryBookFacet(facet_id=ai.id, book_id="single"),
            LibraryBookFacet(facet_id=unknown.id, book_id="unknown"),
            LibraryBookFacet(facet_id=hidden.id, book_id="hidden"),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, user)
    result = ListLibraryGroupings(SqlAlchemyLibraryGroupingQueries(db_session)).execute(
        context=context, kind="AUTHOR", search="林", page=1, page_size=10
    )

    assert result.total == 1
    assert [(group.name, group.book_count) for group in result.groups] == [("林川", 2)]
    assert [book.id for book in result.groups[0].representative_books] == [
        "series-1",
        "series-2",
    ]


def test_grouping_representatives_are_limited_to_authorized_library_scope(
    db_session: Session,
) -> None:
    member = User(
        id="groupings-member",
        email="groupings-member@example.com",
        name="Member",
        password_hash="unused",
        role="member",
    )
    db_session.add(
        Library(
            id="groupings-foreign-library",
            name="Foreign",
            root_path="/groupings-foreign",
            organization_mode="FLAT",
        )
    )
    db_session.flush()
    _book(db_session, book_id="allowed-book", title="Allowed", author="Author")
    _book(
        db_session,
        book_id="foreign-book",
        title="Foreign",
        author="Author",
        library_id="groupings-foreign-library",
    )
    facet = _facet(db_session, "facet-author", "AUTHOR", "Author")
    db_session.add_all(
        [
            member,
            UserLibraryAccess(user_id=member.id, library_id="test-library"),
            LibraryBookFacet(facet_id=facet.id, book_id="allowed-book"),
            LibraryBookFacet(facet_id=facet.id, book_id="foreign-book"),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, member)
    result = ListLibraryGroupings(SqlAlchemyLibraryGroupingQueries(db_session)).execute(
        context=context, kind="AUTHOR", search="", page=1, page_size=10
    )

    assert result.total == 1
    assert result.groups[0].book_count == 1
    assert [book.id for book in result.groups[0].representative_books] == [
        "allowed-book"
    ]
