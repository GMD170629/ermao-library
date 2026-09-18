"""Persist incomplete scan ranges independently of the scan task row.

Revision ID: 0018_library_import_scan_gaps
Revises: 0017_reset_default_cover_paths

Cleaning, replacing or merging a failed scan task must not release a directory
resource whose member list was never fully enumerated. The gap row survives the
task lifecycle and is removed only by a later scan that actually covers the
range.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_library_import_scan_gaps"
down_revision = "0017_reset_default_cover_paths"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "LibraryImportScanGap",
        sa.Column("libraryId", sa.String(length=191), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["libraryId"],
            ["Library.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_LibraryImportScanGap_library",
        ),
        sa.PrimaryKeyConstraint("libraryId"),
    )


def downgrade() -> None:
    op.drop_table("LibraryImportScanGap")
