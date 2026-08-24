"""Stable display-title policy for readable resource assets."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssetTitleCandidate:
    asset_id: str
    metadata_title: str | None
    source_filename: str


_GENERIC_TITLES = frozenset(
    value.casefold()
    for value in ("正文", "audio", "track", "chapter", "音频", "未命名")
)


def _normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def resolve_asset_display_titles(
    candidates: Iterable[AssetTitleCandidate],
) -> dict[str, str]:
    materialized = tuple(candidates)
    normalized = {
        candidate.asset_id: _normalized(candidate.metadata_title)
        for candidate in materialized
    }
    counts = Counter(title.casefold() for title in normalized.values() if title)
    return {
        candidate.asset_id: (
            title
            if title
            and title.casefold() not in _GENERIC_TITLES
            and counts[title.casefold()] == 1
            else candidate.source_filename
        )
        for candidate in materialized
        for title in (normalized[candidate.asset_id],)
    }


__all__ = ["AssetTitleCandidate", "resolve_asset_display_titles"]
