"""Track restartable comic page-index data migration progress.

Revision ID: 0020_comic_page_index
Revises: 0019_writeback_preparation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_comic_page_index"
down_revision: str | Sequence[str] | None = "0019_writeback_preparation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("LibraryFile") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pageIndexVersion",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    op.create_index(
        "LibraryFile_kind_pageIndexVersion_id_idx",
        "LibraryFile",
        ["kind", "pageIndexVersion", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "LibraryFile_kind_pageIndexVersion_id_idx",
        table_name="LibraryFile",
    )
    with op.batch_alter_table("LibraryFile") as batch_op:
        batch_op.drop_column("pageIndexVersion")
