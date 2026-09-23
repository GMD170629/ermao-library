"""Track whether source nodes were seen during a particular scan."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_source_node_scan_seen_generation"
down_revision = "0031_book_import_task_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "LibrarySourceNode",
        sa.Column("scanSeenGeneration", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("LibrarySourceNode", "scanSeenGeneration")
