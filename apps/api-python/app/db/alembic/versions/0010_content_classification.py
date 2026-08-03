"""Separate content classification from concrete volume format.

Revision ID: 0010_content_classification
Revises: 0009_media_version_metadata_contract
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_content_classification"
down_revision: str | Sequence[str] | None = "0009_media_version_metadata_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("MonitorFolder") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mediaKindPolicy",
                sa.String(length=32),
                server_default="MIXED",
                nullable=False,
            )
        )

    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mediaKindPolicy",
                sa.String(length=32),
                server_default="MIXED",
                nullable=False,
            )
        )

    with op.batch_alter_table("LibraryVolume") as batch_op:
        batch_op.add_column(
            sa.Column(
                "classificationSource",
                sa.String(length=32),
                server_default="LEGACY",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "classificationReason",
                sa.String(length=64),
                server_default="LEGACY",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("suggestedMediaKind", sa.String(length=32), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("LibraryVolume") as batch_op:
        batch_op.drop_column("suggestedMediaKind")
        batch_op.drop_column("classificationReason")
        batch_op.drop_column("classificationSource")
    with op.batch_alter_table("ImportTask") as batch_op:
        batch_op.drop_column("mediaKindPolicy")
    with op.batch_alter_table("MonitorFolder") as batch_op:
        batch_op.drop_column("mediaKindPolicy")
