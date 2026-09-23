"""Publication date validation shared by local metadata readers."""

from __future__ import annotations

import re
from datetime import date, datetime


def validated_publication_date(value: str | None) -> str | None:
    """Accept the existing reduced or full ISO publication-date forms."""
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}", value):
            date.fromisoformat(f"{value}-01-01")
        elif re.fullmatch(r"\d{4}-\d{2}", value):
            date.fromisoformat(f"{value}-01")
        else:
            datetime.fromisoformat(value)
    except ValueError:
        # diagnostics-control-flow: Unsupported optional publication dates are omitted.
        return None
    return value
