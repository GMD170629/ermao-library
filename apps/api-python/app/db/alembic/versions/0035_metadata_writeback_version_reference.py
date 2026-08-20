"""Point metadata writeback scopes at LibraryVersion.

Revision ID: 0035_metadata_writeback_version_reference
Revises: 0034_organize_version_reference
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_metadata_writeback_version_reference"
down_revision: str | Sequence[str] | None = "0034_organize_version_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "MetadataWritebackOperation",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_MetadataWritebackOperation_mediaVersionId_LibraryMediaVersion",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_MetadataWritebackOperation_mediaVersionId_LibraryVersion",
            "LibraryVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )

    with op.batch_alter_table(
        "MetadataWritebackPreparation",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_MetadataWritebackPreparation_mediaVersionId_LibraryMediaVersion",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_MetadataWritebackPreparation_mediaVersionId_LibraryVersion",
            "LibraryVersion",
            ["mediaVersionId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )


def downgrade() -> None:
    raise NotImplementedError(
        "0035_metadata_writeback_version_reference does not support downgrade"
    )
