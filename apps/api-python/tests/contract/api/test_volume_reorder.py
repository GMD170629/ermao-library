from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork


def _login_manager(client, db: Session) -> User:
    user = User(
        id="volume-reorder-manager",
        email="volume-reorder@example.com",
        name="Volume Reorder",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200
    return user


def _add_volume_series(db: Session) -> None:
    work = LibraryWork(
        id="reorder-work",
        origin="MANUAL",
        title="Reorder work",
        normalized_title="reorderwork",
        author="Author",
        normalized_author="author",
        work_type="BOOK",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="reorder-media",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volumes = [
        LibraryVolume(
            id=f"reorder-volume-{index}",
            media_version_id=media_version.id,
            title=f"Volume {index}",
            sort_order=index * 1000,
            format="PDF",
            resource_key=f"reorder:{index}",
            import_status="COMPLETED",
        )
        for index in range(1, 4)
    ]
    db.add_all([work, media_version, *volumes])
    db.commit()


def _volume_order(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(LibraryVolume.id)
            .where(LibraryVolume.media_version_id == "reorder-media")
            .order_by(LibraryVolume.sort_order.asc(), LibraryVolume.id.asc())
        ).all()
    )


def test_volume_move_reorders_with_a_dedicated_direction_contract(
    client, db_session: Session
) -> None:
    _login_manager(client, db_session)
    _add_volume_series(db_session)

    moved_down = client.post(
        "/api/works/reorder-work/volumes/reorder-volume-2/move",
        json={"direction": "down"},
    )
    assert moved_down.status_code == 200
    assert _volume_order(db_session) == [
        "reorder-volume-1",
        "reorder-volume-3",
        "reorder-volume-2",
    ]

    moved_up = client.post(
        "/api/works/reorder-work/volumes/reorder-volume-2/move",
        json={"direction": "up"},
    )
    assert moved_up.status_code == 200
    assert _volume_order(db_session) == [
        "reorder-volume-1",
        "reorder-volume-2",
        "reorder-volume-3",
    ]

    boundary = client.post(
        "/api/works/reorder-work/volumes/reorder-volume-1/move",
        json={"direction": "up"},
    )
    assert boundary.status_code == 200
    assert _volume_order(db_session) == [
        "reorder-volume-1",
        "reorder-volume-2",
        "reorder-volume-3",
    ]

    invalid = client.post(
        "/api/works/reorder-work/volumes/reorder-volume-2/move",
        json={"direction": "sideways"},
    )
    assert invalid.status_code == 422


def test_volume_move_rejects_a_volume_outside_the_requested_work(
    client, db_session: Session
) -> None:
    _login_manager(client, db_session)
    _add_volume_series(db_session)
    other_work = LibraryWork(
        id="other-work",
        origin="MANUAL",
        title="Other work",
        normalized_title="otherwork",
        author="Author",
        normalized_author="author",
        work_type="BOOK",
        tags="[]",
    )
    db_session.add(other_work)
    db_session.commit()

    response = client.post(
        "/api/works/other-work/volumes/reorder-volume-2/move",
        json={"direction": "up"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VOLUME_NOT_FOUND"
