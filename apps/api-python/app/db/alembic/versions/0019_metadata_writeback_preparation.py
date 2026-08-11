"""Add durable metadata writeback preparation and worker leases.

Revision ID: 0019_writeback_preparation
Revises: 0018_library_facet_index_version
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.time import TimestampMilliseconds

revision: str = "0019_writeback_preparation"
down_revision: str | Sequence[str] | None = "0018_library_facet_index_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "MetadataLookupTask_status_nextAttemptAt_idx",
        table_name="MetadataLookupTask",
    )
    with op.batch_alter_table("MetadataLookupTask") as batch_op:
        batch_op.add_column(
            sa.Column("leaseOwnerId", sa.String(length=191), nullable=True)
        )
        batch_op.add_column(
            sa.Column("leaseExpiresAt", TimestampMilliseconds(), nullable=True)
        )
    op.create_index(
        "MetadataLookupTask_claim_idx",
        "MetadataLookupTask",
        ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
    )

    op.drop_index(
        "MetadataWritebackTarget_status_createdAt_idx",
        table_name="MetadataWritebackTarget",
    )
    with op.batch_alter_table("MetadataWritebackTarget") as batch_op:
        batch_op.add_column(
            sa.Column("leaseOwnerId", sa.String(length=191), nullable=True)
        )
        batch_op.add_column(
            sa.Column("leaseExpiresAt", TimestampMilliseconds(), nullable=True)
        )
    op.create_index(
        "MetadataWritebackTarget_claim_idx",
        "MetadataWritebackTarget",
        ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
    )

    with op.batch_alter_table("MetadataOpfQueueState") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pendingPreparations",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "MetadataOpfQueueState_pendingPreparations_nonnegative",
            sa.column("pendingPreparations") >= 0,
        )

    op.create_table(
        "MetadataWritebackPreparation",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("operationId", sa.String(length=191), nullable=True),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("mediaVersionId", sa.String(length=191), nullable=True),
        sa.Column("volumeId", sa.String(length=191), nullable=True),
        sa.Column("lookupTaskId", sa.String(length=191), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("idempotencyKey", sa.String(length=64), nullable=False),
        sa.Column("sourceRevision", sa.String(length=191), nullable=False),
        sa.Column("snapshotJson", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="PENDING"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leaseOwnerId", sa.String(length=191), nullable=True),
        sa.Column("leaseExpiresAt", TimestampMilliseconds(), nullable=True),
        sa.Column("nextAttemptAt", TimestampMilliseconds(), nullable=True),
        sa.Column("errorCode", sa.String(length=64), nullable=True),
        sa.Column("errorSummary", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            nullable=False,
            server_default=sa.func.unixepoch() * 1000,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operationId"],
            ["MetadataWritebackOperation.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workId"],
            ["LibraryWork.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mediaVersionId"],
            ["LibraryMediaVersion.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["volumeId"],
            ["LibraryVolume.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lookupTaskId"],
            ["MetadataLookupTask.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotencyKey",
            name="MetadataWritebackPreparation_idempotency_key",
        ),
    )
    op.create_index(
        "MetadataWritebackPreparation_claim_idx",
        "MetadataWritebackPreparation",
        ["status", "nextAttemptAt", "leaseExpiresAt", "createdAt"],
    )
    op.create_index(
        "MetadataWritebackPreparation_operationId_idx",
        "MetadataWritebackPreparation",
        ["operationId"],
    )
    op.create_index(
        "MetadataWritebackPreparation_workId_idx",
        "MetadataWritebackPreparation",
        ["workId"],
    )


def downgrade() -> None:
    op.drop_index(
        "MetadataWritebackPreparation_workId_idx",
        table_name="MetadataWritebackPreparation",
    )
    op.drop_index(
        "MetadataWritebackPreparation_operationId_idx",
        table_name="MetadataWritebackPreparation",
    )
    op.drop_index(
        "MetadataWritebackPreparation_claim_idx",
        table_name="MetadataWritebackPreparation",
    )
    op.drop_table("MetadataWritebackPreparation")

    with op.batch_alter_table("MetadataOpfQueueState") as batch_op:
        batch_op.drop_constraint(
            "MetadataOpfQueueState_pendingPreparations_nonnegative",
            type_="check",
        )
        batch_op.drop_column("pendingPreparations")

    op.drop_index(
        "MetadataWritebackTarget_claim_idx",
        table_name="MetadataWritebackTarget",
    )
    with op.batch_alter_table("MetadataWritebackTarget") as batch_op:
        batch_op.drop_column("leaseExpiresAt")
        batch_op.drop_column("leaseOwnerId")
    op.create_index(
        "MetadataWritebackTarget_status_createdAt_idx",
        "MetadataWritebackTarget",
        ["status", "createdAt"],
    )

    op.drop_index("MetadataLookupTask_claim_idx", table_name="MetadataLookupTask")
    with op.batch_alter_table("MetadataLookupTask") as batch_op:
        batch_op.drop_column("leaseExpiresAt")
        batch_op.drop_column("leaseOwnerId")
    op.create_index(
        "MetadataLookupTask_status_nextAttemptAt_idx",
        "MetadataLookupTask",
        ["status", "nextAttemptAt"],
    )
