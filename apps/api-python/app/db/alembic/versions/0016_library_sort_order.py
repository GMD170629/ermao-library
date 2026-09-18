"""Add a global manual display order to library roots.

Revision ID: 0016_library_sort_order
Revises: 0015_scan_context_version
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_library_sort_order"
down_revision: str | None = "0015_scan_context_version"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "Library",
        sa.Column(
            "sortOrder",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    _backfill_existing_order()


def _backfill_existing_order() -> None:
    """Preserve the previous newest-first display order for existing rows.

    ``0`` stays reserved for libraries created after this migration so they
    appear at the top, matching the historical ``createdAt DESC`` behaviour.
    """

    library = sa.table(
        "Library",
        sa.column("id", sa.String),
        sa.column("sortOrder", sa.Integer),
        sa.column("createdAt", sa.BigInteger),
    )
    bind = op.get_bind()
    ordered_ids = bind.execute(
        sa.select(library.c.id).order_by(
            library.c.createdAt.desc(), library.c.id.desc()
        )
    ).scalars()
    for index, library_id in enumerate(ordered_ids, start=1):
        bind.execute(
            sa.update(library)
            .where(library.c.id == library_id)
            .values(sortOrder=index)
        )


def downgrade() -> None:
    op.drop_column("Library", "sortOrder")
