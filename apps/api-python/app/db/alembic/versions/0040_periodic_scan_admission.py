"""Reset unfinished scans and normalize enabled scans to a fixed daily cycle."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0040_periodic_scan_admission"
down_revision = "0039_generated_metadata_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    tasks = sa.table(
        "LibraryImportTask",
        sa.column("kind", sa.String),
        sa.column("state", sa.String),
    )
    connection.execute(
        sa.delete(tasks).where(
            tasks.c.kind == "SCAN_LIBRARY",
            tasks.c.state.in_(("QUEUED", "RUNNING")),
        )
    )
    settings = sa.table(
        "SystemSetting",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
    )
    interval_key = "libraryScan.intervalMinutes"
    stored = connection.scalar(
        sa.select(settings.c.value).where(settings.c.key == interval_key)
    )
    if stored is None:
        return
    try:
        interval = json.loads(stored)
    except json.JSONDecodeError:
        # Invalid legacy values are outside this migration's normalization scope.
        return
    if type(interval) is int and 5 <= interval <= 1440:
        connection.execute(
            sa.update(settings)
            .where(settings.c.key == interval_key)
            .values(value=json.dumps(1440))
        )


def downgrade() -> None:
    raise RuntimeError(
        "Restore the pre-upgrade backup to downgrade periodic scan admission"
    )
