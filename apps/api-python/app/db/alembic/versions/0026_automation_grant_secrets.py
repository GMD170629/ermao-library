"""Dynamic library grants and authenticated encrypted token recovery."""

import sqlalchemy as sa
from alembic import op

revision = "0026_automation_grant_secrets"
down_revision = "0025_standard_writeback_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "AutomationGrant",
        sa.Column(
            "libraryScope", sa.String(16), nullable=False, server_default="selected"
        ),
    )
    op.add_column(
        "AutomationGrant", sa.Column("tokenCiphertext", sa.String(1024), nullable=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("AutomationGrant") as batch:
        batch.drop_column("tokenCiphertext")
        batch.drop_column("libraryScope")
