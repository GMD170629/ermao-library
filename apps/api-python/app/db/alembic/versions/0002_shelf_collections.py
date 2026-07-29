"""Add shelf collection memberships.

Revision ID: 0002_shelf_collections
Revises: 0001_current_schema
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0002_shelf_collections"
down_revision: str | Sequence[str] | None = "0001_current_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ShelfCollectionMembership",
        sa.Column("collectionId", sa.String(length=191), nullable=False),
        sa.Column("shelfId", sa.String(length=191), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.CheckConstraint(
            sa.column("collectionId") != sa.column("shelfId"),
            name="ShelfCollectionMembership_distinct_shelves_check",
        ),
        sa.ForeignKeyConstraint(
            ["collectionId"],
            ["Shelf.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shelfId"],
            ["Shelf.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collectionId", "shelfId"),
    )
    with op.batch_alter_table("ShelfCollectionMembership") as batch_op:
        batch_op.create_index(
            "ShelfCollectionMembership_shelfId_createdAt_idx",
            ["shelfId", "createdAt"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ShelfCollectionMembership") as batch_op:
        batch_op.drop_index(
            "ShelfCollectionMembership_shelfId_createdAt_idx"
        )
    op.drop_table("ShelfCollectionMembership")
