from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.authorization import AuthorizationContext
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    ReaderResourceProgress,
)
from app.models.auth import User
from app.modules.library.application.request_mutations import BulkReadingStatusMutation
from app.modules.library.infrastructure.request_mutations import (
    SqlAlchemyLibraryRequestMutations,
)
from app.modules.shelf.infrastructure.memberships import (
    SqlAlchemyShelfBookMembership,
)


def _graph(db_session, book_id: str, resource_id: str, resource_format: str) -> None:
    book_path = f"{book_id}/"
    resource_path = f"{book_id}/{resource_id}.{resource_format.lower()}"
    book_node = LibrarySourceNode(
        id=f"{book_id}-node",
        library_id="test-library",
        relative_path=book_path,
        path_key="v1:" + hashlib.sha256(book_path.encode()).hexdigest(),
        name=book_id,
        physical_kind="DIRECTORY",
        observed_size_bytes=None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    resource_node = LibrarySourceNode(
        id=f"{resource_id}-resource-node",
        library_id="test-library",
        relative_path=resource_path,
        path_key="v1:" + hashlib.sha256(resource_path.encode()).hexdigest(),
        name=resource_id,
        physical_kind="REGULAR_FILE",
        observed_size_bytes=10,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )
    db_session.add_all([book_node, resource_node])
    db_session.flush()
    db_session.add(
        LibraryBook(id=book_id, library_id="test-library", source_node_id=book_node.id)
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book_id,
            title=book_id,
            normalized_title=book_id,
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
            adapter_id="audio-file" if resource_format == "AUDIO" else "epub-file",
            adapter_version="1",
            media_kind="AUDIOBOOK" if resource_format == "AUDIO" else "EBOOK",
            format=resource_format,
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(resource_id=resource_id, title=resource_id)
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


def test_bulk_reading_status_targets_resources_by_book_identity(db_session) -> None:
    db_session.add(
        User(
            id="reader-user",
            email="reader@example.test",
            name="Reader",
            password_hash="not-used",
            role="admin",
        )
    )
    db_session.flush()
    _graph(db_session, "reading-ebook", "reading-epub", "EPUB")
    _graph(db_session, "reading-audio", "reading-audio", "AUDIO")
    db_session.commit()
    gateway = SqlAlchemyLibraryRequestMutations(
        db_session,
        shelf_memberships=SqlAlchemyShelfBookMembership(db_session),
        write_events=lambda _db, _events: None,
        write_metadata=lambda _db, _intents: (),
    )
    context = AuthorizationContext(
        user_id="reader-user",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )
    now = datetime.now(UTC)

    updated = gateway.update_reading_status(
        BulkReadingStatusMutation(
            context=context,
            book_ids=("reading-ebook", "reading-audio"),
            status="FINISHED",
            now=now,
        )
    )

    assert updated == 2
    progress = db_session.scalars(
        select(ReaderResourceProgress).order_by(ReaderResourceProgress.resource_id)
    ).all()
    assert [(row.resource_id, row.percent) for row in progress] == [
        ("reading-audio", 100.0),
        ("reading-epub", 100.0),
    ]

    cleared = gateway.update_reading_status(
        BulkReadingStatusMutation(
            context=context,
            book_ids=("reading-ebook", "reading-audio"),
            status="UNREAD",
            now=now,
        )
    )
    assert cleared == 2
    assert db_session.scalars(select(ReaderResourceProgress.id)).all() == []
