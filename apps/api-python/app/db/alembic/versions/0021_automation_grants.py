"""Add fixed-scope automation credentials, without granting any existing user access."""

import sqlalchemy as sa
from alembic import op

revision = "0021_automation_grants"
down_revision = "0020_recheck_scan_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "AutomationGrant",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column(
            "userId",
            sa.String(191),
            sa.ForeignKey("User.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("tokenDigest", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("libraryIds", sa.JSON(), nullable=False),
        sa.Column("writebackTargets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "allowCrossLibrary", sa.Boolean(), nullable=False, server_default="0"
        ),
        sa.Column("createdAt", sa.BigInteger(), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column("revokedAt", sa.BigInteger(), nullable=True),
        sa.Column("lastUsedAt", sa.BigInteger(), nullable=True),
    )
    op.create_index("AutomationGrant_userId_idx", "AutomationGrant", ["userId"])


def downgrade() -> None:
    op.drop_index("AutomationGrant_userId_idx", table_name="AutomationGrant")
    op.drop_table("AutomationGrant")
