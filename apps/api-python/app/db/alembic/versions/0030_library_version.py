"""Create LibraryVersion as a Work-owned source identity.

Revision ID: 0030_library_version
Revises: 0029_library_root
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.time import TimestampMilliseconds

revision: str = "0030_library_version"
down_revision: str | Sequence[str] | None = "0029_library_root"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "LibraryVersion",
        sa.Column("id", sa.String(length=191), nullable=False),
        sa.Column("workId", sa.String(length=191), nullable=False),
        sa.Column("sourceKey", sa.String(length=191), nullable=False),
        sa.Column("sourceName", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            TimestampMilliseconds(),
            server_default=sa.func.unixepoch() * 1000,
            nullable=False,
        ),
        sa.Column("updatedAt", TimestampMilliseconds(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workId"],
            ["LibraryWork.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "LibraryVersion_workId_idx",
        "LibraryVersion",
        ["workId"],
        unique=False,
    )
    op.create_index(
        "LibraryVersion_sourceKey_idx",
        "LibraryVersion",
        ["sourceKey"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError("0030_library_version does not support downgrade")
