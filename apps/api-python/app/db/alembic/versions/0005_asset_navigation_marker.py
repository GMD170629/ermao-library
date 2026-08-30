"""Move lazy publication navigation identity to the immutable asset.

Revision ID: 0005_asset_navigation_marker
Revises: 0004_remove_media_kind
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_asset_navigation_marker"
down_revision: str | Sequence[str] | None = "0004_remove_media_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _navigation_units_copy(*, asset_ondelete: str) -> sa.Table:
    """Describe the existing navigation table with the corrected asset FK."""

    metadata = sa.MetaData()
    return sa.Table(
        "ReadableResourceNavigationUnit",
        metadata,
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("assetId", sa.String(length=191), nullable=True),
        sa.Column("unitType", sa.String(length=191), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("href", sa.Text(), nullable=False),
        sa.Column("mediaType", sa.String(length=191), nullable=True),
        sa.Column("sortOrder", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("startMs", sa.Integer(), nullable=True),
        sa.Column("endMs", sa.Integer(), nullable=True),
        sa.Column("durationMs", sa.Integer(), nullable=True),
        sa.Column("metadataJson", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete=asset_ondelete,
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.Index(
            "ReadableResourceNavigationUnit_resourceId_sortOrder_idx",
            "resourceId",
            "sortOrder",
        ),
        sa.Index(
            "ReadableResourceNavigationUnit_assetId_sortOrder_idx",
            "assetId",
            "sortOrder",
        ),
        sa.Index(
            "ReadableResourceNavigationUnit_resourceId_unitType_sortOrder_key",
            "resourceId",
            "unitType",
            "sortOrder",
            unique=True,
        ),
    )


def upgrade() -> None:
    op.drop_table("PublicationNavigationCache")
    op.create_table(
        "LibraryResourceAssetNavigation",
        sa.Column("assetId", sa.String(length=191), nullable=False),
        sa.Column("chapterCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            sa.column("chapterCount") >= 0,
            name="LibraryResourceAssetNavigation_chapterCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assetId"),
    )
    with op.batch_alter_table(
        "ReadableResourceNavigationUnit",
        copy_from=_navigation_units_copy(asset_ondelete="CASCADE"),
        recreate="always",
    ):
        pass


def downgrade() -> None:
    with op.batch_alter_table(
        "ReadableResourceNavigationUnit",
        copy_from=_navigation_units_copy(asset_ondelete="SET NULL"),
        recreate="always",
    ):
        pass
    op.drop_table("LibraryResourceAssetNavigation")
    op.create_table(
        "PublicationNavigationCache",
        sa.Column("resourceId", sa.String(length=191), nullable=False),
        sa.Column("assetId", sa.String(length=191), nullable=False),
        sa.Column("sourceSizeBytes", sa.Integer(), nullable=False),
        sa.Column("sourceMtimeMs", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=191), nullable=False),
        sa.Column("normalization", sa.String(length=191), nullable=False),
        sa.Column("projectionVersion", sa.Integer(), nullable=False),
        sa.Column("chapterCount", sa.Integer(), nullable=False),
        sa.Column(
            "createdAt",
            sa.BigInteger(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            sa.column("chapterCount") >= 0,
            name="PublicationNavigationCache_chapterCount_check",
        ),
        sa.ForeignKeyConstraint(
            ["assetId"],
            ["LibraryResourceAsset.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resourceId"],
            ["LibraryReadableResource.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("resourceId"),
    )
