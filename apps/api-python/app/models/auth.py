from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import timestamp_ms_server_default


def cuid() -> str:
    return f"py_{uuid4().hex}"


def db_timestamp() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "User"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    email: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    password_hash: Mapped[str] = mapped_column(
        "passwordHash", String(191), nullable=False
    )
    avatar_path: Mapped[str | None] = mapped_column(
        "avatarPath", String(500), nullable=True
    )
    role: Mapped[str] = mapped_column(
        String(191), nullable=False, default="member", server_default="member"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    can_manage_system: Mapped[bool] = mapped_column(
        "canManageSystem", Boolean, nullable=False, default=False, server_default="0"
    )
    can_view_manual_imports: Mapped[bool] = mapped_column(
        "canViewManualImports",
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    authz_version: Mapped[int] = mapped_column(
        "authzVersion", Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )

    sessions: Mapped[list[Session]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def to_auth_view(self) -> dict[str, str | int | bool | None]:
        avatar_version = (
            int(self.updated_at.replace(tzinfo=timezone.utc).timestamp())
            if self.avatar_path
            else None
        )
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "canManageSystem": self.can_manage_system,
            "canViewManualImports": self.can_view_manual_imports,
            "authzVersion": self.authz_version,
            "avatarUrl": f"/api/auth/avatar?v={avatar_version}"
            if avatar_version is not None
            else None,
        }


class Session(Base):
    __tablename__ = "Session"

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    token_hash: Mapped[str] = mapped_column(
        "tokenHash", String(191), unique=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        "expiresAt", TimestampMilliseconds(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )

    user: Mapped[User] = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    __tablename__ = "PasswordResetToken"
    __table_args__ = (
        Index("PasswordResetToken_expiresAt_idx", "expiresAt"),
        Index("PasswordResetToken_userId_createdAt_idx", "userId", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    token_hash: Mapped[str] = mapped_column(
        "tokenHash", String(64), unique=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        "expiresAt", TimestampMilliseconds(), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        "usedAt", TimestampMilliseconds(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )

    user: Mapped[User] = relationship("User", back_populates="password_reset_tokens")


class UserMonitorFolderAccess(Base):
    __tablename__ = "UserMonitorFolderAccess"
    __table_args__ = (Index("UserMonitorFolderAccess_folder_idx", "monitorFolderId"),)

    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    monitor_folder_id: Mapped[str] = mapped_column(
        "monitorFolderId",
        String(191),
        ForeignKey("MonitorFolder.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )


class UserPreference(Base):
    __tablename__ = "UserPreference"
    __table_args__ = (Index("UserPreference_userId_idx", "userId"),)

    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(String(191), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )


class ReaderBookmark(Base):
    __tablename__ = "ReaderBookmark"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "volumeId",
            "contentFingerprint",
            "bookmarkId",
            name="ReaderBookmark_user_volume_fingerprint_bookmark_key",
        ),
        Index("ReaderBookmark_user_volume_idx", "userId", "volumeId"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    user_id: Mapped[str] = mapped_column(
        "userId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    volume_id: Mapped[str] = mapped_column(
        "volumeId",
        String(191),
        ForeignKey("LibraryVolume.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    content_fingerprint: Mapped[str] = mapped_column(
        "contentFingerprint", String(191), nullable=False
    )
    bookmark_id: Mapped[str] = mapped_column("bookmarkId", Text, nullable=False)
    location_json: Mapped[str] = mapped_column("locationJson", Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    percent: Mapped[float] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    bookmark_created_at: Mapped[str] = mapped_column(
        "bookmarkCreatedAt", String(64), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        onupdate=db_timestamp,
    )
