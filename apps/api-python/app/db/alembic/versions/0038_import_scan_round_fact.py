"""Remember whether a scan persisted exact incomplete ranges."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_import_scan_round_fact"
down_revision = "0037_single_import_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "LibraryImportTask",
        sa.Column("scanRoundStarted", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade import scan facts")
