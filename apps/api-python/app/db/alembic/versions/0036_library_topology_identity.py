"""Add path-derived Work and Volume topology identities.

Revision ID: 0036_library_topology_identity
Revises: 0035_metadata_writeback_version_reference
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_library_topology_identity"
down_revision: str | Sequence[str] | None = (
    "0035_metadata_writeback_version_reference"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryWork") as batch_op:
        batch_op.add_column(
            sa.Column("sourceKey", sa.String(length=191), nullable=True)
        )
        batch_op.create_index(
            "LibraryWork_sourceKey_idx", ["sourceKey"], unique=False
        )
        batch_op.create_unique_constraint(
            "LibraryWork_libraryId_sourceKey_key",
            ["libraryId", "sourceKey"],
        )

    with op.batch_alter_table("LibraryVolume") as batch_op:
        batch_op.create_unique_constraint(
            "LibraryVolume_versionId_resourceKey_key",
            ["versionId", "resourceKey"],
        )


def downgrade() -> None:
    raise NotImplementedError(
        "0036_library_topology_identity does not support downgrade"
    )
