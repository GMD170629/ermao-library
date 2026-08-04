"""Add local metadata resolution policy.

Revision ID: 0013_local_metadata_resolution
Revises: 0012_metadata_file_writeback
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_local_metadata_resolution"
down_revision: str | Sequence[str] | None = "0012_metadata_file_writeback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PRIORITY = '["SIDECAR_OPF","EMBEDDED","PATH"]'


def upgrade() -> None:
    with op.batch_alter_table("OrganizePolicy") as batch_op:
        batch_op.add_column(
            sa.Column(
                "preferLocalMetadata",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "localMetadataPriorityJson",
                sa.Text(),
                nullable=False,
                server_default=DEFAULT_PRIORITY,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("OrganizePolicy") as batch_op:
        batch_op.drop_column("localMetadataPriorityJson")
        batch_op.drop_column("preferLocalMetadata")
