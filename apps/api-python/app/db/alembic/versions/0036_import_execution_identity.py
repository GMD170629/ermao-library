"""Allow historical Book and scan tasks alongside independent requests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_import_execution_identity"
down_revision = "0035_directory_member_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes("LibraryImportTask")
    }
    for name in (
        "LibraryImportTask_book_key",
        "LibraryImportTask_scan_queued_key",
        "LibraryImportTask_scan_running_key",
        "LibraryImportTask_book_gate_pending_idx",
        "LibraryImportTask_book_runnable_idx",
    ):
        if name in indexes:
            op.drop_index(name, table_name="LibraryImportTask")
    op.create_index(
        "LibraryImportTask_book_runnable_idx",
        "LibraryImportTask",
        ["state", "createdAt", "id"],
        unique=False,
        sqlite_where=sa.column("kind") == "IMPORT_BOOK",
    )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to downgrade import task identity")
