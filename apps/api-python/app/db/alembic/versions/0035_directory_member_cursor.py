"""Resume a Book's directory resource after a bounded member page."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_directory_member_cursor"
down_revision = "0034_book_completion_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("LibraryImportTask")}
    if "directoryResourceId" not in columns:
        op.add_column("LibraryImportTask", sa.Column("directoryResourceId", sa.String(191), nullable=True))
    if "directoryMemberCursor" not in columns:
        op.add_column("LibraryImportTask", sa.Column("directoryMemberCursor", sa.String(191), nullable=True))
    if "directoryCoverCursor" not in columns:
        op.add_column("LibraryImportTask", sa.Column("directoryCoverCursor", sa.String(191), nullable=True))


def downgrade() -> None:
    op.drop_column("LibraryImportTask", "directoryCoverCursor")
    op.drop_column("LibraryImportTask", "directoryMemberCursor")
    op.drop_column("LibraryImportTask", "directoryResourceId")
