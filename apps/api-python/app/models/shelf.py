from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import cuid, db_timestamp, timestamp_ms_server_default


class Shelf(Base):
    __tablename__ = "Shelf"
    __table_args__ = (
        Index("Shelf_updatedAt_idx", "updatedAt"),
        Index("Shelf_kind_updatedAt_idx", "kind", "updatedAt"),
        Index("Shelf_ownerUserId_updatedAt_idx", "ownerUserId", "updatedAt"),
    )

    id: Mapped[str] = mapped_column(String(191), primary_key=True, default=cuid)
    owner_user_id: Mapped[str | None] = mapped_column(
        "ownerUserId",
        String(191),
        ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(191), nullable=False, default="STATIC", server_default="STATIC")
    rules_json: Mapped[str] = mapped_column("rulesJson", Text, nullable=False, default="{}", server_default="{}")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TimestampMilliseconds(), nullable=False, default=db_timestamp, onupdate=db_timestamp)


class ShelfWork(Base):
    __tablename__ = "ShelfWork"
    __table_args__ = (
        Index("ShelfWork_workId_idx", "workId"),
        Index("ShelfWork_shelfId_createdAt_idx", "shelfId", "createdAt"),
    )

    shelf_id: Mapped[str] = mapped_column(
        "shelfId",
        String(191),
        ForeignKey("Shelf.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    work_id: Mapped[str] = mapped_column(
        "workId",
        String(191),
        ForeignKey("LibraryWork.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
