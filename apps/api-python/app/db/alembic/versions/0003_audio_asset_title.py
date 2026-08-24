"""Persist normalized embedded titles for readable resource assets.

Revision ID: 0003_audio_asset_title
Revises: 0002_library_scan_queue_uniqueness
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Column, Text

revision: str = "0003_audio_asset_title"
down_revision: str | Sequence[str] | None = "0002_library_scan_queue_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "LibraryResourceAssetMetadata",
        Column("title", Text(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("LibraryResourceAssetMetadata") as batch:
        batch.drop_column("title")
