"""Persist resource scan context together with import intent."""

import sqlalchemy as sa
from alembic import op

revision = "0015_scan_context_version"
down_revision = "0014_audio_resource_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "LibraryReadableResource",
        sa.Column("scanContextVersion", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("LibraryReadableResource", "scanContextVersion")
