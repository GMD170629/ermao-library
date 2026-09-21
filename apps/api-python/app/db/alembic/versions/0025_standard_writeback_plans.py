"""Preserve explicit standard-file plans and results after queue consumption."""

import sqlalchemy as sa
from alembic import op

revision = "0025_standard_writeback_plans"
down_revision = "0024_file_move_recovery_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "MetadataStandardWritePlan",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column("grantId", sa.String(191), nullable=False),
        sa.Column("userId", sa.String(191), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "MetadataStandardWriteOperation",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column(
            "planId",
            sa.String(191),
            sa.ForeignKey("MetadataStandardWritePlan.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("grantId", sa.String(191), nullable=False),
        sa.Column("userId", sa.String(191), nullable=False),
        sa.Column("requestId", sa.String(128), nullable=False),
        sa.Column("cancelRequested", sa.Boolean(), nullable=False),
        sa.Column("createdAt", sa.BigInteger(), nullable=False),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "MetadataStandardWriteTarget",
        sa.Column(
            "operationId",
            sa.String(191),
            sa.ForeignKey("MetadataStandardWriteOperation.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("libraryId", sa.String(191), nullable=False),
        sa.Column("queueTargetId", sa.String(191), nullable=False, unique=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("recovery", sa.JSON(), nullable=False),
        sa.Column("errorCode", sa.String(100), nullable=True),
        sa.Column("reservedBytes", sa.BigInteger(), nullable=False),
        sa.Column("recoveryReleased", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "MetadataStandardWriteTarget_libraryId_stage_idx",
        "MetadataStandardWriteTarget",
        ["libraryId", "stage"],
    )


def downgrade() -> None:
    op.drop_table("MetadataStandardWriteTarget")
    op.drop_table("MetadataStandardWriteOperation")
    op.drop_table("MetadataStandardWritePlan")
