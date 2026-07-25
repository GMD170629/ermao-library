"""Create the complete appv2 PostgreSQL schema.

Revision ID: 0001_appv2_initial
Revises:
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
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
    now = datetime.now(UTC)
    connection.execute(
        sa.text(
            """
            INSERT INTO metadata.providers (
                id, slug, name, enabled, priority, config, created_at, updated_at
            ) VALUES (
                :id, 'bangumi', 'Bangumi', false, 100,
                CAST(:config AS jsonb), :now, :now
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {
            "id": uuid.UUID("e80c296f-cbbb-5e45-b862-021888724423"),
            "config": '{"workTypes":["ebook","comic"],"userAgent":""}',
            "now": now,
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    Base.metadata.drop_all(bind=connection, checkfirst=True)
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
