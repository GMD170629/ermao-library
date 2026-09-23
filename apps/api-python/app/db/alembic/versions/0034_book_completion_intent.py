"""Keep committed Book results recoverable across terminal write failures."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_book_completion_intent"
down_revision = "0033_book_scan_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("LibraryImportTask")}
    if "completionOutcome" not in columns:
        op.add_column("LibraryImportTask", sa.Column("completionOutcome", sa.String(32), nullable=True))
    if "completionRetryCount" not in columns:
        op.add_column(
            "LibraryImportTask",
            sa.Column("completionRetryCount", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("LibraryImportTask", "completionRetryCount")
    op.drop_column("LibraryImportTask", "completionOutcome")
