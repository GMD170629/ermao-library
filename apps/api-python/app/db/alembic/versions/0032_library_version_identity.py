"""Enforce unique LibraryVersion identity per work and sourceKey.

Revision ID: 0032_library_version_identity
Revises: 0031_volume_version_reference
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_library_version_identity"
down_revision: str | Sequence[str] | None = "0031_volume_version_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryVersion") as batch_op:
        batch_op.create_unique_constraint(
            "LibraryVersion_workId_sourceKey_key",
            ["workId", "sourceKey"],
        )


def downgrade() -> None:
    raise NotImplementedError(
        "0032_library_version_identity does not support downgrade"
    )
