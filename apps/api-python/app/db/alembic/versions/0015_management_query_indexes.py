"""Add indexes for bounded management-list queries."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0015_management_query_indexes"
down_revision: str | Sequence[str] | None = "0014_dashboard_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx",
        "LibraryWork",
        ["hidden", "normalizedTitle", "normalizedAuthor", "id"],
        unique=False,
    )
    op.create_index(
        "ImportTask_monitorFolderId_createdAt_id_idx",
        "ImportTask",
        ["monitorFolderId", "createdAt", "id"],
        unique=False,
    )
    op.create_index(
        "ImportTask_monitorFolderId_status_createdAt_id_idx",
        "ImportTask",
        ["monitorFolderId", "status", "createdAt", "id"],
        unique=False,
    )
    op.create_index(
        "SystemEvent_createdAt_id_idx",
        "SystemEvent",
        ["createdAt", "id"],
        unique=False,
    )
    op.create_index(
        "SystemEvent_targetType_createdAt_id_idx",
        "SystemEvent",
        ["targetType", "createdAt", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "SystemEvent_targetType_createdAt_id_idx",
        table_name="SystemEvent",
    )
    op.drop_index("SystemEvent_createdAt_id_idx", table_name="SystemEvent")
    op.drop_index(
        "ImportTask_monitorFolderId_status_createdAt_id_idx",
        table_name="ImportTask",
    )
    op.drop_index(
        "ImportTask_monitorFolderId_createdAt_id_idx",
        table_name="ImportTask",
    )
    op.drop_index(
        "LibraryWork_hidden_normalizedTitle_normalizedAuthor_id_idx",
        table_name="LibraryWork",
    )
