"""Version the Publication navigation projection independently of parsing.

Revision ID: 0025_publication_navigation_projection_version
Revises: 0024_publication_navigation_cache
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_publication_navigation_projection_version"
down_revision: str | Sequence[str] | None = "0024_publication_navigation_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("PublicationNavigationCache") as batch_op:
        batch_op.add_column(
            sa.Column(
                "projectionVersion",
                sa.Integer(),
                nullable=True,
            )
        )
    cache = sa.table(
        "PublicationNavigationCache",
        sa.column("projectionVersion", sa.Integer()),
    )
    op.execute(sa.update(cache).values(projectionVersion=1))
    with op.batch_alter_table("PublicationNavigationCache") as batch_op:
        batch_op.alter_column(
            "projectionVersion",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("PublicationNavigationCache") as batch_op:
        batch_op.drop_column("projectionVersion")
