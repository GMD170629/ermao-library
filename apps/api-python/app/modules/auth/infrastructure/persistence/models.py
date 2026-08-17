"""Current authentication ORM models.

The tables deliberately do not import or relate to the legacy ORM models.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.current.registry import CurrentBase


def _new_id() -> str:
    from uuid import uuid4

    return f"current_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CurrentUser(CurrentBase):
    __tablename__ = "User"

    id: Mapped[str] = mapped_column(String(191), primary_key=True)
    authz_version: Mapped[int] = mapped_column(
        "authzVersion", Integer, nullable=False, default=1, server_default="1"
    )
    __table_args__ = (
        CheckConstraint(authz_version > 0, name="User_authzVersion_positive_ck"),
    )
    display_name: Mapped[str] = mapped_column(
        "displayName", String(191), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="admin", server_default="admin"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )


class CurrentAuthIdentity(CurrentBase):
    __tablename__ = "AuthIdentity"
    __table_args__ = (
        UniqueConstraint(
            "provider", "subject", name="AuthIdentity_provider_subject_key"
        ),
        Index("AuthIdentity_userId_idx", "userId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(191), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(
        "passwordHash", String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )


class CurrentSession(CurrentBase):
    __tablename__ = "Session"
    __table_args__ = (Index("Session_userId_idx", "userId"),)

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=_new_id)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column("tokenHash", String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        "expiresAt", TimestampMilliseconds(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", TimestampMilliseconds(), nullable=False, default=_utc_now
    )
