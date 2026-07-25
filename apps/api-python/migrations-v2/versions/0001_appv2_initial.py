"""Create the complete appv2 PostgreSQL schema.

Revision ID: 0001_appv2_initial
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from appv2.composition import models as _models  # noqa: F401
from appv2.platform.database.base import Base

revision: str = "0001_appv2_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = (
    "accounts",
    "catalog",
    "ingestion",
    "metadata",
    "reading",
    "discovery",
    "delivery",
    "operations",
)


def upgrade() -> None:
    connection = op.get_bind()
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    Base.metadata.create_all(bind=connection, checkfirst=False)


def downgrade() -> None:
    connection = op.get_bind()
    Base.metadata.drop_all(bind=connection, checkfirst=True)
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
