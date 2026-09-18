"""Backfill durable scan gaps from pre-existing FAILED scan tasks.

Revision ID: 0019_backfill_scan_gaps
Revises: 0018_library_import_scan_gaps

Runs exactly once. Before the durable gap table existed, a failed scan gated
dependent work through its task row. Converting those rows here preserves the
protection after the task-based gate was removed, without rebuilding recovered
gaps on every startup. Recovery is decided by execution time and covered range,
not by creation order: a task row keeps its ``createdAt`` across retries, so
``finishedAt`` is the only proof a successful scan actually ran after a failure.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0019_backfill_scan_gaps"
down_revision = "0018_library_import_scan_gaps"
branch_labels = None
depends_on = None


def _decode_scopes(raw: object) -> list[tuple[str, bool]] | None:
    if not isinstance(raw, (str, bytes)):
        return None
    data = json.loads(raw)
    if not isinstance(data, list):
        return None
    scopes: list[tuple[str, bool]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = item.get("relativePath")
        recursive = item.get("recursive")
        if isinstance(path, str) and isinstance(recursive, bool):
            scopes.append((path, recursive))
    return scopes


def _resolves(completed: tuple[str, bool], pending: tuple[str, bool]) -> bool:
    done_path, done_recursive = completed
    wait_path, wait_recursive = pending
    if done_recursive:
        if done_path == "":
            return True
        return wait_path == done_path or wait_path.startswith(done_path + "/")
    return wait_path == done_path and not wait_recursive


def _covers(
    completed: list[tuple[str, bool]] | None,
    pending: tuple[str, bool],
) -> bool:
    if completed is None:
        return True
    return any(_resolves(done, pending) for done in completed)


def _merge(
    existing: list[tuple[str, bool]], additions: list[tuple[str, bool]]
) -> list[tuple[str, bool]]:
    merged: list[tuple[str, bool]] = []
    for path, recursive in existing + additions:
        if any(_resolves(kept, (path, recursive)) for kept in merged):
            continue
        merged = [
            kept for kept in merged if not _resolves((path, recursive), kept)
        ]
        merged.append((path, recursive))
    return merged


def backfill_scan_gaps(bind) -> None:
    metadata = sa.MetaData()
    tasks = sa.Table("LibraryImportTask", metadata, autoload_with=bind)
    nodes = sa.Table("LibrarySourceNode", metadata, autoload_with=bind)
    gaps = sa.Table("LibraryImportScanGap", metadata, autoload_with=bind)

    node_paths = {
        row.id: row.relativePath
        for row in bind.execute(sa.select(nodes.c.id, nodes.c.relativePath)).all()
    }
    scan_rows = bind.execute(
        sa.select(
            tasks.c.id,
            tasks.c.libraryId,
            tasks.c.kind,
            tasks.c.state,
            tasks.c.sourceNodeId,
            tasks.c.scanScopes,
            tasks.c.finishedAt,
        ).where(tasks.c.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")))
    ).all()

    def pending_scopes(row) -> list[tuple[str, bool]]:
        if row.kind == "SCAN_LIBRARY":
            scopes = _decode_scopes(row.scanScopes)
            return scopes if scopes else [("", True)]
        if row.kind == "CONTINUE_SOURCE":
            path = node_paths.get(row.sourceNodeId)
            return [(path, True)] if path is not None else []
        # Ordinary import and identification tasks never describe scan coverage.
        return []

    def completed_scopes(row) -> list[tuple[str, bool]] | None:
        if row.kind == "SCAN_LIBRARY":
            return _decode_scopes(row.scanScopes)
        if row.kind == "CONTINUE_SOURCE":
            path = node_paths.get(row.sourceNodeId)
            return [(path, True)] if path is not None else []
        return []

    per_library: dict[str, list[tuple[str, bool]]] = {}
    for row in scan_rows:
        if row.state != "FAILED":
            continue
        for pending in pending_scopes(row):
            # A missing or unprovable finish time is never treated as recovered;
            # only a success that provably finished later and covered the range
            # releases it.
            recovered = False
            if row.finishedAt is not None:
                for later in scan_rows:
                    if (
                        later.state != "SUCCEEDED"
                        or later.libraryId != row.libraryId
                        or later.finishedAt is None
                        or later.finishedAt <= row.finishedAt
                    ):
                        continue
                    if _covers(completed_scopes(later), pending):
                        recovered = True
                        break
            if recovered:
                continue
            per_library.setdefault(row.libraryId, []).append(pending)

    for library_id, scopes in per_library.items():
        found = bind.execute(
            sa.select(gaps.c.scopes).where(gaps.c.libraryId == library_id)
        ).first()
        if found is None:
            existing: list[tuple[str, bool]] = []
            row_exists = False
        else:
            existing = _decode_scopes(found[0]) or []
            row_exists = True
        merged = _merge(existing, scopes)
        payload = json.dumps(
            [
                {"relativePath": path, "recursive": recursive}
                for path, recursive in merged
            ]
        )
        if row_exists:
            bind.execute(
                gaps.update()
                .where(gaps.c.libraryId == library_id)
                .values(scopes=payload)
            )
        else:
            bind.execute(
                gaps.insert().values(libraryId=library_id, scopes=payload)
            )


def upgrade() -> None:
    backfill_scan_gaps(op.get_bind())


def downgrade() -> None:
    # The converted ranges belong to a table owned by 0018; dropping it there
    # removes them. Leaving them on a partial downgrade keeps inputs gated.
    pass
