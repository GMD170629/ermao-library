"""Reserve bounded recovery space for cross-device file moves."""

import sqlalchemy as sa
from alembic import op

revision = "0024_file_move_recovery_limits"
down_revision = "0023_file_move_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "LibraryFileMoveTarget",
        sa.Column("byteCount", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "LibraryFileMoveTarget",
        sa.Column("copyRequired", sa.Boolean(), nullable=False, server_default="0"),
    )
    metadata = sa.MetaData()
    target = sa.Table(
        "LibraryFileMoveTarget",
        metadata,
        sa.Column("operationId", sa.String()),
        sa.Column("ordinal", sa.Integer()),
        sa.Column("byteCount", sa.BigInteger()),
        sa.Column("copyRequired", sa.Boolean()),
    )
    operation = sa.Table(
        "LibraryFileMoveOperation",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("planId", sa.String()),
    )
    plan = sa.Table(
        "LibraryFileMovePlan",
        metadata,
        sa.Column("id", sa.String()),
        sa.Column("payload", sa.JSON()),
    )
    prefix = (
        sa.literal("$.moves[")
        + sa.cast(target.c.ordinal, sa.String())
        + sa.literal("]")
    )

    def value(suffix: str):
        return (
            sa.select(sa.func.json_extract(plan.c.payload, prefix + suffix))
            .select_from(operation.join(plan, plan.c.id == operation.c.planId))
            .where(operation.c.id == target.c.operationId)
            .correlate(target)
            .scalar_subquery()
        )

    op.get_bind().execute(
        target.update().values(
            byteCount=value(".inventory.byte_count"),
            copyRequired=value(".inventory.entries[0].identity.device")
            != value(".destination_inspection.device"),
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("LibraryFileMoveTarget") as batch:
        batch.drop_column("copyRequired")
        batch.drop_column("byteCount")
