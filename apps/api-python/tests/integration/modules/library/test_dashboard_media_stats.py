from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models.auth import User
from app.models.library import LibraryMediaVersion, LibraryWork
from app.modules.library.infrastructure.dashboard import dashboard_summary


def _work(work_id: str, *, hidden: bool = False) -> LibraryWork:
    return LibraryWork(
        id=work_id,
        title=work_id,
        normalized_title=work_id,
        author="作者",
        normalized_author="作者",
        tags="[]",
        hidden=hidden,
    )


def test_dashboard_counts_mixed_media_works_once_per_media_kind(
    db_session: Session,
) -> None:
    user = User(
        email="dashboard-media@example.com",
        name="Dashboard media",
        password_hash="unused",
        role="admin",
    )
    db_session.add(user)
    db_session.add_all(
        [
            _work("mixed"),
            _work("ebook-only"),
            _work("hidden", hidden=True),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            LibraryMediaVersion(id="mixed-ebook", work_id="mixed", media_kind="EBOOK"),
            LibraryMediaVersion(id="mixed-comic", work_id="mixed", media_kind="COMIC"),
            LibraryMediaVersion(id="ebook-only-media", work_id="ebook-only", media_kind="EBOOK"),
            LibraryMediaVersion(id="hidden-audio", work_id="hidden", media_kind="AUDIOBOOK"),
        ]
    )
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
