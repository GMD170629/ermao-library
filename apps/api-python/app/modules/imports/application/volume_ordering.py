"""Deterministic ordering policy for imported non-audio volumes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.modules.imports.application.ports import LibraryImportStore
from app.modules.imports.application.query_ports import ImportLibraryQueries


@dataclass(frozen=True)
class VolumeOrderingEntry:
    volume_id: str
    title: str
    volume_index: float | None
    sort_order: int


def natural_title_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Build a case- and width-insensitive natural filename ordering key."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", normalized)
        if part
    )


def desired_volume_sort_orders(
    entries: list[VolumeOrderingEntry],
) -> dict[str, int]:
    """Order numbered volumes numerically, then unnumbered volumes naturally."""

    numbered = sorted(
        (entry for entry in entries if entry.volume_index is not None),
        key=lambda entry: (
            float(entry.volume_index or 0),
            natural_title_key(entry.title),
            entry.volume_id,
        ),
    )
    unnumbered = sorted(
        (entry for entry in entries if entry.volume_index is None),
        key=lambda entry: (natural_title_key(entry.title), entry.volume_id),
    )
    desired = {
        entry.volume_id: int(float(entry.volume_index or 0) * 1000)
        for entry in numbered
    }
    next_order = max(desired.values(), default=-1000) + 1000
    for entry in unnumbered:
        desired[entry.volume_id] = next_order
        next_order += 1000
    return desired


def normalize_media_version_volume_order(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    media_version_id: str,
) -> None:
    """Persist one media version's deterministic volume order."""

    entries = [
        VolumeOrderingEntry(
            volume_id=str(row["id"]),
            title=str(row["title"]),
            volume_index=(
                float(row["volumeIndex"])
                if row.get("volumeIndex") is not None
                else None
            ),
            sort_order=int(row["sortOrder"]),
        )
        for row in queries.list_volume_ordering_for_media_version(media_version_id)
    ]
    desired = desired_volume_sort_orders(entries)
    for entry in entries:
        sort_order = desired[entry.volume_id]
        if sort_order != entry.sort_order:
            store.update_library_volume(
                entry.volume_id,
                columns={"sortOrder": sort_order},
            )
