"""Cache deterministic publication render artifacts.

Revision ID: 0026_publication_render_cache
Revises: 0025_publication_navigation_projection_version
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0026_publication_render_cache"
down_revision: str | Sequence[str] | None = (
    "0025_publication_navigation_projection_version"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "PublicationRenderCache",
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=False),
        sa.Column("originalFileHash", sa.String(length=191), nullable=False),
        sa.Column("parser", sa.String(length=191), nullable=False),
        sa.Column("normalization", sa.String(length=191), nullable=False),
        sa.Column("relativePath", sa.String(length=1024), nullable=False),
        sa.Column("contentHash", sa.String(length=191), nullable=False),
        sa.Column("sizeBytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("unreadableResourceCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint(
            '"sizeBytes" > 0',
            name="PublicationRenderCache_sizeBytes_check",
        ),
        sa.CheckConstraint(
            '"unreadableResourceCount" >= 0',
            name="PublicationRenderCache_unreadableResourceCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"],
            ["LibraryVolume.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fileId"],
            ["LibraryFile.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("volumeId"),
    )


def downgrade() -> None:
    op.drop_table("PublicationRenderCache")
