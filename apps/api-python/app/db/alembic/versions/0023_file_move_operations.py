"""Freeze move plans and persist per-target recovery checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0023_file_move_operations"
down_revision = "0022_automation_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "LibraryFileMovePlan",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column("grantId", sa.String(191), nullable=False),
        sa.Column("userId", sa.String(191), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "LibraryFileMoveOperation",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column(
            "planId",
            sa.String(191),
            sa.ForeignKey("LibraryFileMovePlan.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("grantId", sa.String(191), nullable=False),
        sa.Column("userId", sa.String(191), nullable=False),
        sa.Column("requestId", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("cancelRequested", sa.Boolean(), nullable=False),
        sa.Column("createdAt", sa.BigInteger(), nullable=False),
        sa.Column("updatedAt", sa.BigInteger(), nullable=False),
        sa.Column("errorCode", sa.String(100), nullable=True),
    )
    op.create_index(
        "LibraryFileMoveOperation_status_createdAt_idx",
        "LibraryFileMoveOperation",
        ["status", "createdAt"],
    )
    op.create_table(
        "LibraryFileMoveTarget",
        sa.Column(
            "operationId",
            sa.String(191),
            sa.ForeignKey("LibraryFileMoveOperation.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("sourceLibraryId", sa.String(191), nullable=False),
        sa.Column("destinationLibraryId", sa.String(191), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("recovery", sa.JSON(), nullable=False),
        sa.Column("errorCode", sa.String(100), nullable=True),
    )
    for column in ("sourceLibraryId", "destinationLibraryId"):
        op.create_index(
            f"LibraryFileMoveTarget_{column}_idx", "LibraryFileMoveTarget", [column]
        )


def downgrade() -> None:
    op.drop_table("LibraryFileMoveTarget")
    op.drop_table("LibraryFileMoveOperation")
    op.drop_table("LibraryFileMovePlan")
