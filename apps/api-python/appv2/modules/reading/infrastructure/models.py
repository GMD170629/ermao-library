from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class ProgressRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "progress"
    __table_args__ = (
        CheckConstraint("percentage >= 0 AND percentage <= 1", name="percentage_valid"),
        UniqueConstraint("user_id", "edition_id", name="user_edition"),
        {"schema": "reading"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.editions.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    percentage: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BookmarkRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "edition_id", "client_id", name="user_edition_client"),
        {"schema": "reading"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.editions.id"), nullable=False)
    client_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str | None] = mapped_column(String(500))
    position: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)


class ReaderPreferenceRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "scope", "target_id", name="user_scope_target"),
        {"schema": "reading"},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[uuid.UUID | None]
    values: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class LocationClaimRecord(UUIDPrimaryKey, Base):
    __tablename__ = "location_claims"
    __table_args__ = (
        UniqueConstraint("edition_id", name="edition"),
        {"schema": "reading"},
    )

    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.editions.id"), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
