"""Persist automation idempotency receipts in the business transaction."""

import sqlalchemy as sa
from alembic import op

revision = "0022_automation_receipts"
down_revision = "0021_automation_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "AutomationReceipt",
        sa.Column(
            "grantId",
            sa.String(191),
            sa.ForeignKey("AutomationGrant.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("requestId", sa.String(128), primary_key=True),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("createdAt", sa.BigInteger(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("AutomationReceipt")
