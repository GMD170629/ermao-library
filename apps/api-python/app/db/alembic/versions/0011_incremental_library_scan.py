"""Persist incremental scan scope and empty-library protection."""

import sqlalchemy as sa
from alembic import op

revision = "0011_incremental_library_scan"
down_revision = "0010_book_metadata_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "Library",
        sa.Column(
            "allowEmptyLibraryCleanup", sa.Boolean(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "LibraryImportTask", sa.Column("scanScopes", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade library scanning")
