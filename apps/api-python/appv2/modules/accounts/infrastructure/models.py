from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class UserRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member')", name="role_valid"),
        {"schema": "accounts"},
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="zh-CN")
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionRecord(UUIDPrimaryKey, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_expires", "user_id", "expires_at"),
        {"schema": "accounts"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordResetRecord(UUIDPrimaryKey, Base):
    __tablename__ = "password_resets"
    __table_args__ = (
        Index("ix_password_resets_user_expires", "user_id", "expires_at"),
        {"schema": "accounts"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountPreferenceRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="user_key"),
        {"schema": "accounts"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
