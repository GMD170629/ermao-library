from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models.auth import User
from app.models.library import (
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries


def test_bookshelf_projection_uses_current_users_continue_volume_progress(
    db_session: Session,
) -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    current_user = User(
        id="bookshelf-user",
        email="bookshelf-user@example.test",
        name="Bookshelf user",
        password_hash="test",
        role="admin",
    )
    other_user = User(
        id="other-bookshelf-user",
        email="other-bookshelf-user@example.test",
        name="Other user",
        password_hash="test",
        role="member",
    )
    work = LibraryWork(
        id="bookshelf-work",
        origin="MANUAL",
        title="Bookshelf work",
        normalized_title="bookshelfwork",
        author="Author",
        normalized_author="author",
        tags="[]",
        hidden=False,
        created_at=now,
        updated_at=now,
    )
    media_version = LibraryMediaVersion(
        id="bookshelf-media",
        work_id=work.id,
        media_kind="EBOOK",
        created_at=now,
        updated_at=now,
    )
    first_volume = LibraryVolume(
        id="bookshelf-volume-1",
        media_version_id=media_version.id,
        origin="MANUAL",
        title="Volume 1",
        sort_order=0,
        format="EPUB",
        resource_key="bookshelf:volume:1",
        hidden=False,
        created_at=now,
        updated_at=now,
    )
    second_volume = LibraryVolume(
        id="bookshelf-volume-2",
        media_version_id=media_version.id,
        origin="MANUAL",
        title="Volume 2",
        sort_order=1,
        format="EPUB",
        resource_key="bookshelf:volume:2",
        hidden=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all(
        [current_user, other_user, work, media_version, first_volume, second_volume]
    )
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadingProgress(
                id="bookshelf-progress-current-1",
                user_id=current_user.id,
                volume_id=first_volume.id,
                reader_type="reflowable",
                position="first",
                percent=35.5,
                extra="{}",
                progressed_at=now,
                created_at=now,
                updated_at=now,
            ),
            LibraryReadingProgress(
                id="bookshelf-progress-current-2",
                user_id=current_user.id,
                volume_id=second_volume.id,
                reader_type="reflowable",
                position="second",
                percent=100,
                extra="{}",
                progressed_at=now + timedelta(minutes=1),
                created_at=now,
                updated_at=now + timedelta(minutes=1),
            ),
            LibraryReadingProgress(
                id="bookshelf-progress-other",
                user_id=other_user.id,
                volume_id=first_volume.id,
                reader_type="reflowable",
                position="other",
                percent=88,
                extra="{}",
                progressed_at=now + timedelta(minutes=2),
                created_at=now,
                updated_at=now + timedelta(minutes=2),
            ),
        ]
    )
    db_session.commit()
    context = AuthorizationContext(
        user_id=current_user.id,
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        monitor_folder_ids=(),
        authz_version=1,
    )

    items = ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db_session)).execute(
        context=context,
        work_ids=(work.id,),
    )

    assert len(items) == 1
    assert items[0].available_media_kinds == ("EBOOK",)
    assert items[0].progress == 35.5
