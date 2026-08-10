"""Track restartable library facet index repair progress.

Revision ID: 0018_library_facet_index_version
Revises: 0017_metadata_opf_queue_state
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_library_facet_index_version"
down_revision: str | Sequence[str] | None = "0017_metadata_opf_queue_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "LibraryWork",
        sa.Column(
            "facetIndexVersion",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "LibraryWork_facetIndexVersion_id_idx",
        "LibraryWork",
        ["facetIndexVersion", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("LibraryWork_facetIndexVersion_id_idx", table_name="LibraryWork")
    with op.batch_alter_table("LibraryWork", schema=None) as batch_op:
        batch_op.drop_column("facetIndexVersion")
