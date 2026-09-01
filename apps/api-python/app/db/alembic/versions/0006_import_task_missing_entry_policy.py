"""Persist the source-scan missing-entry reconciliation policy.

Revision ID: 0006_import_task_missing_entry_policy
Revises: 0005_asset_navigation_marker
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_import_task_missing_entry_policy"
down_revision: str | Sequence[str] | None = "0005_asset_navigation_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryImportTask") as batch:
        batch.add_column(
            sa.Column(
                "missingEntryPolicy",
                sa.String(length=32),
                server_default="PRESERVE",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "LibraryImportTask_missingEntryPolicy_check",
            sa.column("missingEntryPolicy").in_(("PRESERVE", "PRUNE_MISSING")),
        )


def downgrade() -> None:
    with op.batch_alter_table("LibraryImportTask") as batch:
        batch.drop_constraint(
            "LibraryImportTask_missingEntryPolicy_check",
            type_="check",
        )
        batch.drop_column("missingEntryPolicy")
