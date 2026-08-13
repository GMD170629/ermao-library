"""Invalidate pre-morphology Reader v4 progress state.

Revision ID: 0022_reader_v4_location_morphologies
Revises: 0021_reader_v4_exact_progress

Reader v4 was unreleased. The contract is intentionally replaced in place, so
old snapshots and idempotency receipts cannot be interpreted by the new readers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_reader_v4_location_morphologies"
down_revision: str | Sequence[str] | None = "0021_reader_v4_exact_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    progress = sa.table(
        "LibraryReadingProgress",
        sa.column("schemaVersion", sa.Integer()),
        sa.column("revision", sa.Integer()),
        sa.column("sourceProtocol", sa.String(length=32)),
    )
    mutations = sa.table(
        "ReaderProgressMutation",
        sa.column("id", sa.String(length=191)),
    )
    op.execute(sa.delete(mutations))
    op.execute(
        sa.delete(progress).where(
            sa.or_(
                progress.c.schemaVersion == 4,
                progress.c.revision > 0,
                progress.c.sourceProtocol == "SHUKU_READER_V4",
            )
        )
    )


def downgrade() -> None:
    # Invalidated locations cannot be reconstructed safely.
    pass
