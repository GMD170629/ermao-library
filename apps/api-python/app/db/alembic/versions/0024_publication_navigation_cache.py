"""Make Publication TOC the lazy reflowable navigation authority.

Revision ID: 0024_publication_navigation_cache
Revises: 0023_publication_full_hash_identity
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0024_publication_navigation_cache"
down_revision: str | Sequence[str] | None = "0023_publication_full_hash_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFLOWABLE_FORMATS = ("epub", "mobi", "azw", "azw3", "prc", "fb2", "txt")


def upgrade() -> None:
    op.create_table(
        "PublicationNavigationCache",
        sa.Column("volumeId", sa.String(length=191), nullable=False),
        sa.Column("fileId", sa.String(length=191), nullable=False),
        sa.Column("originalFileHash", sa.String(length=191), nullable=False),
        sa.Column("parser", sa.String(length=191), nullable=False),
        sa.Column("normalization", sa.String(length=191), nullable=False),
        sa.Column("chapterCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint(
            '"chapterCount" >= 0',
            name="PublicationNavigationCache_chapterCount_check",
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

    volumes = sa.table(
        "LibraryVolume",
        sa.column("id", sa.String(length=191)),
        sa.column("format", sa.String(length=191)),
        sa.column("chapterCount", sa.Integer()),
    )
    units = sa.table(
        "LibraryReadingUnit",
        sa.column("volumeId", sa.String(length=191)),
        sa.column("unitType", sa.String(length=191)),
    )
    reflowable_volume_ids = sa.select(volumes.c.id).where(
        sa.func.lower(volumes.c.format).in_(_REFLOWABLE_FORMATS)
    )
    op.execute(
        sa.delete(units).where(
            units.c.unitType == "chapter",
            units.c.volumeId.in_(reflowable_volume_ids),
        )
    )
    op.execute(
        sa.update(volumes)
        .where(sa.func.lower(volumes.c.format).in_(_REFLOWABLE_FORMATS))
        .values(chapterCount=None)
    )


def downgrade() -> None:
    # Removed legacy rows were not authoritative and cannot be reconstructed.
    op.drop_table("PublicationNavigationCache")
