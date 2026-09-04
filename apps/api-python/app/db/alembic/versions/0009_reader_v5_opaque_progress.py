"""Add the isolated Reader v5 opaque-progress tables.

Reader v4 and legacy/OPDS progress rows remain in their original tables.  This
revision deliberately does not backfill or delete any of those rows.

Revision ID: 0009_reader_v5_opaque_progress
Revises: 0008_foreign_key_lookup_indexes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_reader_v5_opaque_progress"
down_revision: str | Sequence[str] | None = "0008_foreign_key_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ReaderResourceProgressV5",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("clientId", sa.String(length=256), nullable=False),
        sa.Column("mutationId", sa.String(length=36), nullable=False),
        sa.Column("locatorJson", sa.Text(), nullable=False),
        sa.Column("presentationJson", sa.Text(), nullable=False),
        sa.Column("displayPercent", sa.Float(), nullable=False),
        sa.Column("totalProgression", sa.Float(), nullable=False),
        sa.Column("currentHref", sa.String(length=8192), nullable=True),
        sa.Column("chapterHref", sa.String(length=8192), nullable=True),
        sa.Column("chapterTitle", sa.String(length=4096), nullable=True),
        sa.Column("chapterIndex", sa.Integer(), nullable=True),
        sa.Column("pageNumber", sa.Integer(), nullable=True),
        sa.Column("pageTotal", sa.Integer(), nullable=True),
        sa.Column("playbackPositionMillis", sa.Integer(), nullable=True),
        sa.Column("playbackDurationMillis", sa.Integer(), nullable=True),
        sa.Column("capturedAt", sa.BigInteger(), nullable=False),
        sa.Column(
            "receivedAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column(
            "updatedAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ReaderResourceProgressV5_resourceId_idx",
        "ReaderResourceProgressV5",
        ["resourceId"],
    )
    op.create_index(
        "ReaderResourceProgressV5_userId_updatedAt_resourceId_idx",
        "ReaderResourceProgressV5",
        ["userId", "updatedAt", "resourceId"],
    )
    op.create_index(
        "ReaderResourceProgressV5_userId_resourceId_key",
        "ReaderResourceProgressV5",
        ["userId", "resourceId"],
        unique=True,
    )

    op.create_table(
        "ReaderProgressMutationV5",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("mutationId", sa.String(length=36), nullable=False),
        sa.Column("clientId", sa.String(length=256), nullable=False),
        sa.Column("acceptedRevision", sa.Integer(), nullable=False),
        sa.Column("payloadHash", sa.String(length=64), nullable=False),
        sa.Column("capturedAt", sa.BigInteger(), nullable=False),
        sa.Column("receivedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            "mutationId",
            name="ReaderProgressMutationV5_userId_resourceId_mutationId_key",
        ),
    )
    op.create_index(
        "ReaderProgressMutationV5_userId_resourceId_acceptedRevision_idx",
        "ReaderProgressMutationV5",
        ["userId", "resourceId", "acceptedRevision"],
    )
    op.create_index(
        "ReaderProgressMutationV5_resourceId_idx",
        "ReaderProgressMutationV5",
        ["resourceId"],
    )

    op.create_table(
        "ReaderResourceReadingStatusV5",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "updatedAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            name="ReaderResourceReadingStatusV5_userId_resourceId_key",
        ),
    )
    op.create_index(
        "ReaderResourceReadingStatusV5_resourceId_idx",
        "ReaderResourceReadingStatusV5",
        ["resourceId"],
    )

    op.create_table(
        "ReaderBookmarkV5",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("bookmarkId", sa.String(length=5000), nullable=False),
        sa.Column("locatorJson", sa.Text(), nullable=False),
        sa.Column("presentationJson", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("bookmarkCreatedAt", sa.BigInteger(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.Column(
            "updatedAt",
            sa.BigInteger(),
            server_default=(sa.func.unixepoch() * 1000),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "resourceId",
            "bookmarkId",
            name="ReaderBookmarkV5_user_resource_bookmark_key",
        ),
    )
    op.create_index(
        "ReaderBookmarkV5_user_resource_createdAt_bookmarkId_idx",
        "ReaderBookmarkV5",
        ["userId", "resourceId", "bookmarkCreatedAt", "bookmarkId"],
    )
    op.create_index(
        "ReaderBookmarkV5_resourceId_idx",
        "ReaderBookmarkV5",
        ["resourceId"],
    )


def downgrade() -> None:
    op.drop_index(
        "ReaderBookmarkV5_resourceId_idx",
        table_name="ReaderBookmarkV5",
    )
    op.drop_index(
        "ReaderBookmarkV5_user_resource_createdAt_bookmarkId_idx",
        table_name="ReaderBookmarkV5",
    )
    op.drop_table("ReaderBookmarkV5")
    op.drop_index(
        "ReaderResourceReadingStatusV5_resourceId_idx",
        table_name="ReaderResourceReadingStatusV5",
    )
    op.drop_table("ReaderResourceReadingStatusV5")
    op.drop_index(
        "ReaderProgressMutationV5_resourceId_idx",
        table_name="ReaderProgressMutationV5",
    )
    op.drop_index(
        "ReaderProgressMutationV5_userId_resourceId_acceptedRevision_idx",
        table_name="ReaderProgressMutationV5",
    )
    op.drop_table("ReaderProgressMutationV5")
    op.drop_index(
        "ReaderResourceProgressV5_userId_resourceId_key",
        table_name="ReaderResourceProgressV5",
    )
    op.drop_index(
        "ReaderResourceProgressV5_userId_updatedAt_resourceId_idx",
        table_name="ReaderResourceProgressV5",
    )
    op.drop_index(
        "ReaderResourceProgressV5_resourceId_idx",
        table_name="ReaderResourceProgressV5",
    )
    op.drop_table("ReaderResourceProgressV5")
