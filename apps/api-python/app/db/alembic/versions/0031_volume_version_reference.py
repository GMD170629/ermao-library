"""Point LibraryVolume at LibraryVersion instead of LibraryMediaVersion.

Revision ID: 0031_volume_version_reference
Revises: 0030_library_version
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_volume_version_reference"
down_revision: str | Sequence[str] | None = "0030_library_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryVolume") as batch_op:
        batch_op.drop_index("LibraryVolume_mediaVersionId_sortOrder_idx")
        batch_op.drop_index("LibraryVolume_mediaVersionId_volumeIndex_idx")
        batch_op.drop_index("LibraryVolume_mediaVersionId_hidden_idx")
        batch_op.drop_column("mediaVersionId")
        batch_op.add_column(sa.Column("versionId", sa.String(length=191), nullable=False))
        batch_op.create_foreign_key(
            "LibraryVolume_versionId_fkey",
            "LibraryVersion",
            ["versionId"],
            ["id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
        batch_op.create_index(
            "LibraryVolume_versionId_sortOrder_idx",
            ["versionId", "sortOrder"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryVolume_versionId_volumeIndex_idx",
            ["versionId", "volumeIndex"],
            unique=False,
        )
        batch_op.create_index(
            "LibraryVolume_versionId_hidden_idx",
            ["versionId", "hidden"],
            unique=False,
        )


def downgrade() -> None:
    raise NotImplementedError(
        "0031_volume_version_reference does not support downgrade"
    )
