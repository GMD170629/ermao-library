from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.authorization import AuthorizationContext
from app.models.auth import User
from app.models.library import (
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.application.request_mutations import BulkReadingStatusMutation
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.modules.library.infrastructure.request_mutations import (
    SqlAlchemyLibraryRequestMutations,
)


def _add_work_with_volume(
    db_session,
    *,
    work_id: str,
    volume_id: str,
    format: str,
) -> None:
    db_session.add(
        LibraryWork(
            id=work_id,
            library_id="test-library",
            title=work_id,
            normalized_title=work_id,
            author="Author",
            normalized_author="author",
            tags="[]",
        )
    )
    db_session.flush()
    version_id = f"version-{work_id}"
    db_session.add(
        LibraryVersion(
            id=version_id,
            work_id=work_id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    db_session.flush()
    db_session.add(
        LibraryVolume(
            id=volume_id,
            version_id=version_id,
            title=volume_id,
            sort_order=0,
            format=format,
            resource_key=f"resource:{volume_id}",
            import_status="COMPLETED",
        )
    )
    db_session.flush()


def test_bulk_reading_status_uses_structural_versions_without_media_versions(
    db_session,
) -> None:
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
    _add_work_with_volume(
        db_session,
        work_id="reading-ebook",
        volume_id="reading-epub-volume",
        format="EPUB",
    )
    _add_work_with_volume(
        db_session,
        work_id="reading-audio",
        volume_id="reading-audio-volume",
        format="M4B",
    )
    gateway = SqlAlchemyLibraryRequestMutations(
        db_session,
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
            work_ids=("reading-ebook", "reading-audio"),
            status="FINISHED",
            now=now,
        )
    )

    assert updated == 2
    progress = db_session.scalars(
        select(LibraryReadingProgress).order_by(LibraryReadingProgress.volume_id)
    ).all()
    assert [(row.volume_id, row.reader_type, row.percent) for row in progress] == [
        ("reading-audio-volume", "audio", 100.0),
        ("reading-epub-volume", "epub", 100.0),
    ]

    cleared = gateway.update_reading_status(
        BulkReadingStatusMutation(
            context=context,
            work_ids=("reading-ebook", "reading-audio"),
            status="UNREAD",
            now=now,
        )
    )

    assert cleared == 2
    assert db_session.scalars(select(LibraryReadingProgress.id)).all() == []
