"""Add revisioned exact Reader v4 progress and bounded mutation receipts.

Revision ID: 0021_reader_v4_exact_progress
Revises: 0020_comic_page_index
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0021_reader_v4_exact_progress"
down_revision: str | Sequence[str] | None = "0020_comic_page_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False)
        )

    op.create_table(
        "ReaderProgressMutation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("userId", sa.String(length=191), nullable=False),
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("mutationId", sa.String(length=36), nullable=False),
        sa.Column("clientId", sa.String(length=256), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("locatorJson", sa.Text(), nullable=False),
        sa.Column("contentFingerprint", sa.String(length=191), nullable=False),
        sa.Column("displayPercent", sa.Float(), nullable=False),
        sa.Column("capturedAt", TimestampMilliseconds(), nullable=False),
        sa.Column("receivedAt", TimestampMilliseconds(), nullable=False),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["User.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"],
            ["LibraryVolume.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "volumeId",
            "mutationId",
            name="ReaderProgressMutation_userId_volumeId_mutationId_key",
        ),
    )
    op.create_index(
        "ReaderProgressMutation_userId_volumeId_revision_idx",
        "ReaderProgressMutation",
        ["userId", "volumeId", "revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ReaderProgressMutation_userId_volumeId_revision_idx",
        table_name="ReaderProgressMutation",
    )
    op.drop_table("ReaderProgressMutation")
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.drop_column("revision")
