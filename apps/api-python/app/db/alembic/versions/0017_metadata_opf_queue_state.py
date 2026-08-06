"""Add bounded OPF queue accounting.

Revision ID: 0017_metadata_opf_queue_state
Revises: 0016_reader_progress_v3
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from app.core.time import TimestampMilliseconds

revision: str = "0017_metadata_opf_queue_state"
down_revision: str | Sequence[str] | None = "0016_reader_progress_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    writeback_target = sa.table(
        "MetadataWritebackTarget", sa.column("id", sa.String(length=191))
    )
    pending_targets = int(
        op.get_bind().scalar(
            sa.select(sa.func.count()).select_from(writeback_target)
        )
        or 0
    )
    table = op.create_table(
        "MetadataOpfQueueState",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("pendingTargets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.CheckConstraint(
            '"pendingTargets" >= 0',
            name="MetadataOpfQueueState_pendingTargets_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": "default",
                "pendingTargets": pending_targets,
                "updatedAt": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("MetadataOpfQueueState")
