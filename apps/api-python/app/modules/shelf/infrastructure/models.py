from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, column
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models.common import db_timestamp, timestamp_ms_server_default


class ShelfCollectionMembership(Base):
    __tablename__ = "ShelfCollectionMembership"
    __table_args__ = (
        CheckConstraint(
            column("collectionId") != column("shelfId"),
            name="ShelfCollectionMembership_distinct_shelves_check",
        ),
        Index(
            "ShelfCollectionMembership_shelfId_createdAt_idx",
            "shelfId",
            "createdAt",
        ),
    )

    collection_id: Mapped[str] = mapped_column(
        "collectionId",
        String(191),
        ForeignKey("Shelf.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    shelf_id: Mapped[str] = mapped_column(
        "shelfId",
        String(191),
        ForeignKey("Shelf.id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TimestampMilliseconds(),
        nullable=False,
        default=db_timestamp,
        server_default=timestamp_ms_server_default(),
    )
