"""Durable plans and per-target progress for permanent file deletion."""

import sqlalchemy as sa
from alembic import op

revision = "0029_file_deletions"
down_revision = "0028_automation_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "FileDeletePlan",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column("user_id", sa.String(191), nullable=False),
        sa.Column("grant_id", sa.String(191), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_FileDeletePlan_user_id", "FileDeletePlan", ["user_id"])
    op.create_index("ix_FileDeletePlan_grant_id", "FileDeletePlan", ["grant_id"])


def downgrade() -> None:
    op.drop_table("FileDeletePlan")
