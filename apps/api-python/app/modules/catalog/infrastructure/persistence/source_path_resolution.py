"""Exact raw-slot resolution and first-observation SourceEntry identities."""

from __future__ import annotations

import secrets

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from .enums import SlotState, SourceEntryType
from .models import LibrarySourceEntry

SOURCE_QUERY_CHUNK = 400


def paths_with_ancestors(
    paths: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Return raw paths plus every non-root ancestor in stable input order."""

    return tuple(
        dict.fromkeys(
            path[:depth] for path in paths for depth in range(1, len(path) + 1)
        )
    )


def resolve_raw_paths(
    session: Session,
    library_id: str,
    paths: tuple[tuple[str, ...], ...],
) -> dict[tuple[str, ...], LibrarySourceEntry]:
    root = session.scalar(
        select(LibrarySourceEntry).where(
            LibrarySourceEntry.library_id == library_id,
            LibrarySourceEntry.entry_type == SourceEntryType.SYNTHETIC_ROOT,
        )
    )
    if root is None:
        return {}
    resolved: dict[tuple[str, ...], LibrarySourceEntry] = {(): root}
    for depth in range(1, max((len(path) for path in paths), default=0) + 1):
        target_paths = tuple(
            path
            for path in paths
            if len(path) >= depth and path[: depth - 1] in resolved
        )
        slot_keys = tuple(
            dict.fromkeys(
                (resolved[path[: depth - 1]].id, path[depth - 1])
                for path in target_paths
            )
        )
        rows_by_slot: dict[tuple[str, str], LibrarySourceEntry] = {}
        for offset in range(0, len(slot_keys), SOURCE_QUERY_CHUNK):
            for row in session.scalars(
                select(LibrarySourceEntry)
                .where(
                    LibrarySourceEntry.library_id == library_id,
                    LibrarySourceEntry.slot_state != SlotState.RETIRED,
                    tuple_(
                        LibrarySourceEntry.parent_entry_id,
                        LibrarySourceEntry.local_name,
                    ).in_(slot_keys[offset : offset + SOURCE_QUERY_CHUNK]),
                )
                .with_for_update()
            ):
                if row.parent_entry_id is not None:
                    rows_by_slot[(row.parent_entry_id, row.local_name)] = row
        for path in target_paths:
            parent = resolved[path[: depth - 1]]
            resolved_row = rows_by_slot.get((parent.id, path[depth - 1]))
            if resolved_row is not None:
                resolved[path[:depth]] = resolved_row
    return {path: resolved[path] for path in paths if path in resolved}


def new_opaque_source_id() -> str:
    """Allocate a path-independent first-observation SourceEntry identity."""

    return f"source_{secrets.token_hex(16)}"


__all__ = [
    "SOURCE_QUERY_CHUNK",
    "new_opaque_source_id",
    "paths_with_ancestors",
    "resolve_raw_paths",
]
