"""Add indexes for bounded dashboard and active-library queries."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0014_dashboard_query_indexes"
down_revision: str | Sequence[str] | None = "0013_local_metadata_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "LibraryWork_hidden_createdAt_id_idx",
        "LibraryWork",
        ["hidden", "createdAt", "id"],
        unique=False,
    )
    op.create_index(
        "LibraryVolume_mediaVersionId_hidden_monitorFolderId_idx",
        "LibraryVolume",
        ["mediaVersionId", "hidden", "monitorFolderId"],
        unique=False,
    )
    op.create_index(
        "LibraryReadingProgress_userId_updatedAt_volumeId_idx",
        "LibraryReadingProgress",
        ["userId", "updatedAt", "volumeId"],
        unique=False,
    )
    op.create_index(
        "UserMediaHistory_userId_updatedAt_mediaVersionId_idx",
        "UserMediaHistory",
        ["userId", "updatedAt", "mediaVersionId"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "UserMediaHistory_userId_updatedAt_mediaVersionId_idx",
        table_name="UserMediaHistory",
    )
    op.drop_index(
        "LibraryReadingProgress_userId_updatedAt_volumeId_idx",
        table_name="LibraryReadingProgress",
    )
    op.drop_index(
        "LibraryVolume_mediaVersionId_hidden_monitorFolderId_idx",
        table_name="LibraryVolume",
    )
    op.drop_index(
        "LibraryWork_hidden_createdAt_id_idx",
        table_name="LibraryWork",
    )
