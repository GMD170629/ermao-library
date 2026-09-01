"""Add direct indexes for source-node foreign-key lookups.

Revision ID: 0007_source_node_lookup_indexes
Revises: 0006_import_task_missing_entry_policy
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_source_node_lookup_indexes"
down_revision: str | Sequence[str] | None = "0006_import_task_missing_entry_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "LibrarySourceNode_parentId_idx",
        "LibrarySourceNode",
        ["parentId"],
    )
    op.create_index(
        "LibraryImportTask_sourceNodeId_idx",
        "LibraryImportTask",
        ["sourceNodeId"],
    )


def downgrade() -> None:
    op.drop_index(
        "LibraryImportTask_sourceNodeId_idx",
        table_name="LibraryImportTask",
    )
    op.drop_index(
        "LibrarySourceNode_parentId_idx",
        table_name="LibrarySourceNode",
    )
