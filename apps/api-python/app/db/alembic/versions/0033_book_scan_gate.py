"""Keep a recoverable scan gate projection outside the Book claim query.

Historical Book rows start unknown. The worker refreshes them in bounded pages
from the durable LibraryImportScanGap; no incomplete range is released on upgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_book_scan_gate"
down_revision = "0032_source_node_scan_seen_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("LibraryImportTask")}
    if "scanGateBlocked" not in columns:
        op.add_column(
            "LibraryImportTask",
            sa.Column("scanGateBlocked", sa.Boolean(), nullable=True),
        )
    indexes = {item["name"] for item in inspector.get_indexes("LibraryImportTask")}
    if "LibraryImportTask_book_runnable_idx" in indexes:
        op.drop_index("LibraryImportTask_book_runnable_idx", table_name="LibraryImportTask")
    op.create_index(
        "LibraryImportTask_book_runnable_idx",
        "LibraryImportTask",
        ["state", "scanGateBlocked", "nextAttemptAt", "createdAt", "id"],
        sqlite_where=sa.column("kind") == "IMPORT_BOOK",
    )
    if "LibraryImportTask_book_gate_pending_idx" not in indexes:
        op.create_index(
            "LibraryImportTask_book_gate_pending_idx",
            "LibraryImportTask",
            ["id"],
            sqlite_where=sa.and_(
                sa.column("kind") == "IMPORT_BOOK",
                sa.column("state") == "QUEUED",
                sa.column("scanGateBlocked").is_(None),
            ),
        )
    node_indexes = {
        item["name"] for item in inspector.get_indexes("LibrarySourceNode")
    }
    if "LibrarySourceNode_libraryId_relativePath_idx" not in node_indexes:
        op.create_index(
            "LibrarySourceNode_libraryId_relativePath_idx",
            "LibrarySourceNode",
            ["libraryId", "relativePath"],
        )


def downgrade() -> None:
    op.drop_index(
        "LibrarySourceNode_libraryId_relativePath_idx",
        table_name="LibrarySourceNode",
    )
    op.drop_index(
        "LibraryImportTask_book_gate_pending_idx", table_name="LibraryImportTask"
    )
    op.drop_index("LibraryImportTask_book_runnable_idx", table_name="LibraryImportTask")
    op.create_index(
        "LibraryImportTask_book_runnable_idx",
        "LibraryImportTask",
        ["state", "nextAttemptAt", "createdAt", "id"],
        sqlite_where=sa.column("kind") == "IMPORT_BOOK",
    )
    op.drop_column("LibraryImportTask", "scanGateBlocked")
