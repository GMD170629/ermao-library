"""Point organize targets at LibraryVersion.

Revision ID: 0034_organize_version_reference
Revises: 0033_remove_user_media_history
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_organize_version_reference"
down_revision: str | Sequence[str] | None = "0033_remove_user_media_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("OrganizeJob", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "fk_OrganizeJob_mediaVersionId_LibraryMediaVersion",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_OrganizeJob_mediaVersionId_LibraryVersion",
            "LibraryVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )

    with op.batch_alter_table("MetadataLookupTask", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "fk_MetadataLookupTask_mediaVersionId_LibraryMediaVersion",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_MetadataLookupTask_mediaVersionId_LibraryVersion",
            "LibraryVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        )


def downgrade() -> None:
    raise NotImplementedError(
        "0034_organize_version_reference does not support downgrade"
    )
