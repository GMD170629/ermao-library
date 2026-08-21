from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.models.auth import User
from app.modules.library.infrastructure.dashboard import (
    dashboard_summary,
    list_management_books,
)


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _source_node(
    node_id: str,
    relative_path: str,
    *,
    directory: bool,
    observed_at: datetime,
) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rstrip("/").rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 123,
        observed_mtime_ns=0,
        observed_at=observed_at,
    )


def _book_graph(
    book_id: str,
    *,
    formats: tuple[tuple[str, str], ...],
    hidden: bool = False,
    observed_at: datetime,
) -> tuple[
    list[LibrarySourceNode],
    LibraryBook,
    LibraryBookMetadata,
    list[LibraryReadableResource],
]:
    book_node = _source_node(
        f"{book_id}-node",
        f"{book_id}/",
        directory=True,
        observed_at=observed_at,
    )
    book = LibraryBook(
        id=book_id,
        library_id="test-library",
        source_node_id=book_node.id,
        visibility_state="HIDDEN" if hidden else "VISIBLE",
    )
    metadata = LibraryBookMetadata(
        book_id=book_id,
        title=book_id,
        normalized_title=book_id.casefold(),
        author="作者",
        normalized_author="作者",
    )
    resource_nodes: list[LibrarySourceNode] = []
    resources: list[LibraryReadableResource] = []
    for index, (media_kind, file_format) in enumerate(formats):
        resource_id = f"{book_id}-resource-{index}"
        resource_node = _source_node(
            f"{resource_id}-node",
            f"{book_id}/{resource_id}.{file_format.lower()}",
            directory=False,
            observed_at=observed_at,
        )
        resource_nodes.append(resource_node)
        resources.append(
            LibraryReadableResource(
                id=resource_id,
                library_id="test-library",
                book_id=book_id,
                source_node_id=resource_node.id,
                adapter_id="test-adapter",
                adapter_version="1",
                media_kind=media_kind,
                format=file_format,
                import_state="READY",
            )
        )
    return [book_node, *resource_nodes], book, metadata, resources


def test_dashboard_counts_mixed_media_books_once_per_media_kind(
    db_session: Session,
) -> None:
    user = User(
        email="dashboard-media@example.com",
        name="Dashboard media",
        password_hash="unused",
        role="admin",
    )
    now = datetime.now(UTC)
    graphs = [
        _book_graph(
            "mixed",
            formats=(("EBOOK", "EPUB"), ("COMIC", "CBZ")),
            observed_at=now,
        ),
        _book_graph(
            "ebook-only",
            formats=(("EBOOK", "EPUB"),),
            observed_at=now,
        ),
        _book_graph(
            "hidden",
            formats=(("AUDIOBOOK", "M4B"),),
            hidden=True,
            observed_at=now,
        ),
    ]
    db_session.add(user)
    for nodes, _book, _metadata, _resources in graphs:
        db_session.add_all(nodes)
    db_session.flush()
    for _nodes, book, metadata, resources in graphs:
        db_session.add(book)
        db_session.flush()
        db_session.add(metadata)
        db_session.add_all(resources)
    db_session.commit()

    summary = dashboard_summary(
        db_session,
        authorization_context(db_session, user),
        user.id,
    )

    assert summary["totalBooks"] == 2
    assert summary["ebookBooks"] == 2
    assert summary["comicBooks"] == 1
    assert summary["audiobookBooks"] == 0
    assert "novelBooks" not in summary

    books = {book["id"]: book for book in list_management_books(db_session)}
    assert books["mixed"]["availableMediaKinds"] == ["EBOOK", "COMIC"]
    assert books["ebook-only"]["availableMediaKinds"] == ["EBOOK"]
