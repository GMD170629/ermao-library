"""Bound active library scans to one queued and one running task per library.

Revision ID: 0002_library_scan_queue_uniqueness
Revises: 0001_library_topology_baseline
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import (
    Column,
    Index,
    MetaData,
    String,
    Table,
    and_,
    delete,
    select,
    update,
)

revision: str = "0002_library_scan_queue_uniqueness"
down_revision: str | Sequence[str] | None = "0001_library_topology_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _task_table() -> Table:
    metadata = MetaData()
    return Table(
        "LibraryImportTask",
        metadata,
        Column("id", String(191), primary_key=True),
        Column("libraryId", String(191), nullable=False),
        Column("kind", String(32), nullable=False),
        Column("state", String(32), nullable=False),
        Column("errorSummary", String(), nullable=True),
        Column("createdAt", String(), nullable=False),
    )


def _coalesce_active_scans(task: Table, *, state: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        select(task.c.id, task.c.libraryId)
        .where(task.c.kind == "SCAN_LIBRARY", task.c.state == state)
        .order_by(task.c.libraryId.asc(), task.c.createdAt.asc(), task.c.id.asc())
    ).all()
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for task_id, library_id in rows:
        if library_id in seen:
            duplicate_ids.append(task_id)
        else:
            seen.add(library_id)
    if not duplicate_ids:
        return
    if state == "QUEUED":
        connection.execute(delete(task).where(task.c.id.in_(tuple(duplicate_ids))))
        return
    connection.execute(
        update(task)
        .where(task.c.id.in_(tuple(duplicate_ids)))
        .values(state="FAILED", errorSummary="DUPLICATE_RUNNING_SCAN_REPAIRED")
    )


def upgrade() -> None:
    task = _task_table()
    _coalesce_active_scans(task, state="QUEUED")
    _coalesce_active_scans(task, state="RUNNING")
    bind = op.get_bind()
    Index(
        "LibraryImportTask_scan_queued_key",
        task.c.libraryId,
        unique=True,
        sqlite_where=and_(task.c.kind == "SCAN_LIBRARY", task.c.state == "QUEUED"),
    ).create(bind=bind, checkfirst=True)
    Index(
        "LibraryImportTask_scan_running_key",
        task.c.libraryId,
        unique=True,
        sqlite_where=and_(task.c.kind == "SCAN_LIBRARY", task.c.state == "RUNNING"),
    ).create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    task = _task_table()
    Index("LibraryImportTask_scan_running_key", task.c.libraryId).drop(
        bind=bind, checkfirst=True
    )
    Index("LibraryImportTask_scan_queued_key", task.c.libraryId).drop(
        bind=bind, checkfirst=True
    )
