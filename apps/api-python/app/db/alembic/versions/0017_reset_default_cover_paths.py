"""Reset legacy metadata rows that stored the bundled fallback cover path.

Revision ID: 0017_reset_default_cover_paths
Revises: 0016_library_sort_order

Older imports persisted ``default-book-cover-v1.png`` into metadata while a
Book had no real cover. That stale value let OPF writeback re-publish the
bundled asset to disk per Book, so clear it back to "no cover".

The upgrade is idempotent: rows already reset (or never affected) are left
untouched. The data cleanup is irreversible and intentionally has no downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017_reset_default_cover_paths"
down_revision: str | None = "0016_library_sort_order"
branch_labels: str | None = None
depends_on: str | None = None

_DEFAULT_COVER_PATTERN = "%default-book-cover-%"


def _metadata_table(name: str) -> sa.TableClause:
    return sa.table(
        name,
        sa.column("coverPath", sa.Text),
        sa.column("coverStatus", sa.String),
    )


def _clear_metadata_covers(table_name: str) -> None:
    table = _metadata_table(table_name)
    op.get_bind().execute(
        sa.update(table)
        .where(sa.func.lower(table.c.coverPath).like(_DEFAULT_COVER_PATTERN))
        .values(coverPath=None, coverStatus="PENDING")
    )


def _clear_asset_covers() -> None:
    asset = sa.table(
        "LibraryResourceAsset",
        sa.column("localCoverPath", sa.Text),
    )
    op.get_bind().execute(
        sa.update(asset)
        .where(sa.func.lower(asset.c.localCoverPath).like(_DEFAULT_COVER_PATTERN))
        .values(localCoverPath=None)
    )


def upgrade() -> None:
    for table_name in (
        "LibraryBookMetadata",
        "LibraryReadableResourceMetadata",
        "LibrarySourceNodeMetadata",
    ):
        _clear_metadata_covers(table_name)
    _clear_asset_covers()


def downgrade() -> None:
    # A data cleanup cannot distinguish reset rows from covers that never
    # existed, so downgrading would fabricate state. Nothing to do.
    pass
