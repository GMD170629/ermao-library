"""SQLAlchemy queries for Auth user administration projections."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    authorization_context,
    is_admin,
    read_user_preferences,
)
from app.core.i18n import configured_locale
from app.models.auth import User
from app.modules.auth.infrastructure.user_data import list_library_ids


def list_users(db: Session) -> tuple[User, ...]:
    return tuple(
        db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc()))
    )


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def email_in_use(
    db: Session, email: str, *, excluding_user_id: str | None = None
) -> bool:
    statement = select(User.id).where(func.lower(User.email) == email)
    if excluding_user_id is not None:
        statement = statement.where(User.id != excluding_user_id)
    return db.scalar(statement.limit(1)) is not None


def active_admin_count(db: Session, *, excluding_user_id: str | None = None) -> int:
    statement = (
        select(func.count())
        .select_from(User)
        .where(
            User.role == "admin",
            User.status == "active",
        )
    )
    if excluding_user_id is not None:
        statement = statement.where(User.id != excluding_user_id)
    return int(db.scalar(statement) or 0)


def refresh_user(db: Session, user: User) -> User:
    db.refresh(user)
    return user


def user_view(db: Session, user: User) -> dict[str, Any]:
    preferences = read_user_preferences(db, user.id)
    locale = preferences.get("locale")
    if locale not in {"zh-CN", "en-US"}:
        locale = configured_locale(db)
    return {
        **user.to_auth_view(),
        "locale": locale,
        "libraryIds": [] if is_admin(user) else list_library_ids(db, user.id),
        "authorization": authorization_context(db, user).to_view(),
        "createdAt": user.created_at,
        "updatedAt": user.updated_at,
    }
