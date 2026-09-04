from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext
from app.models import (
    LibraryBook,
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
)
from app.models.auth import User
from app.modules.reader.infrastructure.v5_library_queries import (
    reader_v5_progress_expression,
    reader_v5_reading_status_expression,
)
from tests.contract.api.test_library_smart_filters import _book, _ready_resource


def _admin_context(user_id: str) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=user_id,
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )


def test_v5_status_aggregates_explicit_completion_across_resources(
    db_session: Session,
) -> None:
    user = User(
        id="v5-status-user",
        email="v5-status@example.test",
        name="Reader v5 status",
        password_hash="unused",
        role="admin",
    )
    db_session.add(user)
    db_session.flush()
    _book(db_session, book_id="v5-multi", title="Multi", author="Author")
    _ready_resource(db_session, book_id="v5-multi", resource_id="v5-multi-1")
    _ready_resource(db_session, book_id="v5-multi", resource_id="v5-multi-2")
    _book(db_session, book_id="v5-single", title="Single", author="Author")
    _ready_resource(db_session, book_id="v5-single", resource_id="v5-single-1")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ReaderResourceReadingStatusV5(
                user_id=user.id,
                resource_id="v5-multi-1",
                status="FINISHED",
                updated_at=now,
            ),
            ReaderResourceReadingStatusV5(
                user_id=user.id,
                resource_id="v5-single-1",
                status="FINISHED",
                updated_at=now,
            ),
        ]
    )
    db_session.commit()

    context = _admin_context(user.id)

    def ids(status: str) -> list[str]:
        predicate = reader_v5_reading_status_expression(
            context=context,
            user_id=user.id,
            book_id_expression=LibraryBook.id,
            status=status,
        )
        return db_session.scalars(
            select(LibraryBook.id).where(predicate).order_by(LibraryBook.id)
        ).all()

    assert ids("UNREAD") == []
    assert ids("READING") == ["v5-multi"]
    assert ids("FINISHED") == ["v5-single"]


def test_v5_progress_projection_is_user_scoped_and_none_is_null(
    db_session: Session,
) -> None:
    first = User(
        id="v5-progress-first",
        email="v5-progress-first@example.test",
        name="First",
        password_hash="unused",
        role="admin",
    )
    second = User(
        id="v5-progress-second",
        email="v5-progress-second@example.test",
        name="Second",
        password_hash="unused",
        role="admin",
    )
    db_session.add_all([first, second])
    db_session.flush()
    _book(db_session, book_id="v5-scope-first", title="First", author="Author")
    _ready_resource(
        db_session,
        book_id="v5-scope-first",
        resource_id="v5-scope-first-resource",
    )
    _book(db_session, book_id="v5-scope-second", title="Second", author="Author")
    _ready_resource(
        db_session,
        book_id="v5-scope-second",
        resource_id="v5-scope-second-resource",
    )
    now = datetime.now(UTC)
    position_json = (
        '{"displayPercent":50,"totalProgression":0.5,"currentHref":null,'
        '"chapter":null,"page":null,"playback":null}'
    )
    db_session.add_all(
        [
            ReaderResourceProgressV5(
                user_id=first.id,
                resource_id="v5-scope-first-resource",
                client_id="first-client",
                mutation_id="00000000-0000-4000-8000-000000000001",
                locator_json="{}",
                presentation_json=position_json,
                display_percent=50,
                total_progression=0.5,
                captured_at=now,
                received_at=now,
                updated_at=now,
                revision=1,
            ),
            ReaderResourceProgressV5(
                user_id=second.id,
                resource_id="v5-scope-second-resource",
                client_id="second-client",
                mutation_id="00000000-0000-4000-8000-000000000002",
                locator_json="{}",
                presentation_json=position_json,
                display_percent=100,
                total_progression=1,
                captured_at=now,
                received_at=now,
                updated_at=now,
                revision=1,
            ),
        ]
    )
    db_session.commit()

    context = _admin_context(first.id)
    expression = reader_v5_progress_expression(
        context=context,
        user_id=first.id,
        book_id_expression=LibraryBook.id,
        field="display_percent",
    )
    rows = db_session.execute(
        select(LibraryBook.id, expression.label("progress")).order_by(LibraryBook.id)
    ).all()
    assert rows == [
        ("v5-scope-first", 50.0),
        ("v5-scope-second", None),
    ]

    null_expression = reader_v5_progress_expression(
        context=context,
        user_id=None,
        book_id_expression=LibraryBook.id,
        field="display_percent",
    )
    null_rows = db_session.scalars(
        select(null_expression).select_from(LibraryBook).order_by(LibraryBook.id)
    ).all()
    assert null_rows == [None, None]
