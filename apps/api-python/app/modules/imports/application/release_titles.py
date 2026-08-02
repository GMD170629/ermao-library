"""Release-title parsing used by the compatibility tracking endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.imports.application.identity_policy import (
    contains_explicit_volume_range,
    split_explicit_volume,
)


@dataclass(frozen=True)
class ParsedReleaseTitle:
    series_name: str
    volume_index: float


def parse_release_title(value: str) -> ParsedReleaseTitle | None:
    explicit_volume = split_explicit_volume(value)
    if explicit_volume is not None:
        series_name, volume_index = explicit_volume
        return ParsedReleaseTitle(series_name=series_name, volume_index=volume_index)
    if contains_explicit_volume_range(value):
        return None
    normalized = re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()
    for pattern in (
        r"^(.+?)\s*(?:vol\.?|volume)\s*(\d+(?:\.\d+)?)$",
        r"^(.+?)\s*(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"^(.+?)\s+(\d+(?:\.\d+)?)$",
    ):
        match = re.match(pattern, normalized, re.IGNORECASE)
        if match:
            series_name = re.sub(r"\s+", " ", match.group(1)).strip()
            if series_name:
                return ParsedReleaseTitle(
                    series_name=series_name,
                    volume_index=float(match.group(2)),
                )
    return None
