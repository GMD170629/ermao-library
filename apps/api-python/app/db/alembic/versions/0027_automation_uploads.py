"""Durable MCP attachment progress; content stays outside the database."""

import sqlalchemy as sa
from alembic import op

revision = "0027_automation_uploads"
down_revision = "0026_automation_grant_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "AutomationUpload",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("userId", sa.String(191), nullable=False),
        sa.Column("grantId", sa.String(191), nullable=False),
        sa.Column("libraryId", sa.String(191), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sizeBytes", sa.BigInteger(), nullable=False),
        sa.Column("createdAt", sa.BigInteger(), nullable=False),
        sa.Column("expiresAt", sa.BigInteger(), nullable=False),
        sa.Column("cleanupAfter", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "AutomationUpload_grantId_status_idx", "AutomationUpload", ["grantId", "status"]
    )
    op.create_index("AutomationUpload_expiresAt_idx", "AutomationUpload", ["expiresAt"])
    op.create_index(
        "AutomationUpload_userId_createdAt_idx",
        "AutomationUpload",
        ["userId", "createdAt"],
    )


def downgrade() -> None:
    op.drop_table("AutomationUpload")
