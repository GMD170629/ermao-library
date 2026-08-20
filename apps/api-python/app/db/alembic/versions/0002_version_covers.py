"""add independent version covers

Revision ID: 0002_version_covers
Revises: 0001_library_topology_baseline
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_version_covers"
down_revision: str | Sequence[str] | None = "0001_library_topology_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryVersion") as batch_op:
        batch_op.add_column(sa.Column("coverPath", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "coverStatus",
                sa.String(length=32),
                server_default="PENDING",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("LibraryVersion") as batch_op:
        batch_op.drop_column("coverStatus")
        batch_op.drop_column("coverPath")
