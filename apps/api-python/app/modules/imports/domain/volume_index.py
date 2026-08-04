"""Pure parsing rules for structured current-volume metadata fields."""

from __future__ import annotations

import math
import re
import unicodedata

_NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
_ORDINAL_PREFIX = chr(0x7B2C)
_VOLUME_UNITS = "".join(
    chr(codepoint) for codepoint in (0x5377, 0x518C, 0x90E8, 0x96C6)
)
_STRUCTURED_PATTERNS = (
    re.compile(rf"^{_NUMBER}$", re.IGNORECASE),
    re.compile(rf"^{_NUMBER}\s*(?:of|/)\s*\d+(?:\.\d+)?$", re.IGNORECASE),
    re.compile(rf"^(?:vol(?:ume)?\.?|book)\s*{_NUMBER}$", re.IGNORECASE),
    re.compile(
        rf"^{re.escape(_ORDINAL_PREFIX)}\s*{_NUMBER}\s*[{re.escape(_VOLUME_UNITS)}]$",
        re.IGNORECASE,
    ),
)


def parse_structured_volume_index(value: object | None) -> float | None:
    """Return an explicit current-volume number, never a collection total.

    Format adapters call this only for fields whose schema means volume/number.
    Total-count phrases are intentionally rejected because they do not express
    the current publication's position.
    """

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not normalized:
        return None
    for pattern in _STRUCTURED_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        parsed = float(match.group("value"))
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    return None
