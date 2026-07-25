from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from appv2.platform.database.base import Base, Timestamped, UUIDPrimaryKey


class WorkRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "works"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('book', 'comic', 'pdf', 'audiobook', 'text')",
            name="media_type_valid",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status_valid"),
        Index("ix_works_title", "title"),
        {"schema": "catalog"},
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    cover_key: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class EditionRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "editions"
    __table_args__ = (
        CheckConstraint(
            "format IN ('epub', 'pdf', 'cbz', 'cbr', 'txt', 'mobi', 'azw3', 'audio')",
            name="format_valid",
        ),
        Index("ix_editions_work_created", "work_id", "created_at"),
        {"schema": "catalog"},
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.works.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class VolumeRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "volumes"
    __table_args__ = (
        UniqueConstraint("edition_id", "sort_order", name="edition_sort_order"),
        {"schema": "catalog"},
    )

    edition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.editions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)


class FileRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("checksum", "storage_path", name="checksum_storage_path"),
        Index("ix_files_edition", "edition_id"),
        {"schema": "catalog"},
    )

    edition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.editions.id", ondelete="CASCADE"), nullable=False
    )
    volume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.volumes.id", ondelete="SET NULL")
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)


class ShelfRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "shelves"
    __table_args__ = (
        CheckConstraint("kind IN ('manual', 'smart')", name="kind_valid"),
        UniqueConstraint("owner_id", "name", name="owner_name"),
        {"schema": "catalog"},
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    rules: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ShelfItemRecord(UUIDPrimaryKey, Base):
    __tablename__ = "shelf_items"
    __table_args__ = (
        UniqueConstraint("shelf_id", "work_id", name="shelf_work"),
        {"schema": "catalog"},
    )

    shelf_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.shelves.id", ondelete="CASCADE"), nullable=False
    )
    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.works.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CategoryRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("kind", "name", name="kind_name"),
        {"schema": "catalog"},
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class WorkCategoryRecord(UUIDPrimaryKey, Base):
    __tablename__ = "work_categories"
    __table_args__ = (
        UniqueConstraint("work_id", "category_id", name="work_category"),
        {"schema": "catalog"},
    )

    work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.works.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.categories.id", ondelete="CASCADE"), nullable=False
    )


class LibraryOperationRecord(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "library_operations"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'reverted', 'failed')", name="status_valid"),
        {"schema": "catalog"},
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    undo_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
