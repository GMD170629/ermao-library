"""Add logical progression time and source metadata.

Revision ID: 0011_reader_progress_sources
Revises: 0010_content_classification
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0011_reader_progress_sources"
down_revision: str | Sequence[str] | None = "0010_content_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.add_column(
            sa.Column("progressedAt", TimestampMilliseconds(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sourceProtocol", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sourceDeviceName", sa.String(length=191), nullable=True)
        )

    progress = sa.table(
        "LibraryReadingProgress",
        sa.column("updatedAt", sa.BigInteger()),
        sa.column("progressedAt", sa.BigInteger()),
        sa.column("sourceProtocol", sa.String(length=32)),
        sa.column("sourceDeviceName", sa.String(length=191)),
    )
    op.get_bind().execute(
        sa.update(progress).values(
            progressedAt=progress.c.updatedAt,
            sourceProtocol="SHUKU_WEB",
            sourceDeviceName="Shuku Web Reader",
        )
    )

    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.alter_column(
            "progressedAt",
            existing_type=TimestampMilliseconds(),
            nullable=False,
            server_default=sa.func.unixepoch() * 1000,
        )
        batch_op.alter_column(
            "sourceProtocol",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default="SHUKU_WEB",
        )


def downgrade() -> None:
    with op.batch_alter_table("LibraryReadingProgress") as batch_op:
        batch_op.drop_column("sourceDeviceName")
        batch_op.drop_column("sourceProtocol")
        batch_op.drop_column("progressedAt")
