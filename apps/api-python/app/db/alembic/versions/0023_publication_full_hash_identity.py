"""Allow the same immutable publication bytes to back multiple volumes.

Revision ID: 0023_publication_full_hash_identity
Revises: 0022_reader_v4_location_morphologies
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_publication_full_hash_identity"
down_revision: str | Sequence[str] | None = "0022_reader_v4_location_morphologies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # fullHash is publication identity, not a row identity. The existing
    # LibraryFile_fullHash_idx continues to provide non-unique lookup support.
    op.drop_index("LibraryFile_fullHash_key", table_name="LibraryFile")


def downgrade() -> None:
    # This intentionally fails rather than discarding legitimate duplicate
    # rows if data written after the upgrade cannot satisfy the old invariant.
    op.create_index(
        "LibraryFile_fullHash_key",
        "LibraryFile",
        ["fullHash"],
        unique=True,
    )
