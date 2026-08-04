"""Pure work-identity resolution after local metadata has been finalized."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.modules.imports.application.identity_policy import (
    UNKNOWN_AUTHOR,
    normalize_identity_part,
)

WorkIdentityKind = Literal["ISBN", "IDENTIFIER", "SERIES_AUTHOR", "TITLE_AUTHOR"]


@dataclass(frozen=True, slots=True)
class WorkIdentityDecision:
    """The deterministic database identity derived from final publication metadata."""

    merge_key: str
    kind: WorkIdentityKind


def resolve_work_identity(
    *,
    title: str,
    author: str | None,
    isbn: str | None = None,
    identifier: str | None = None,
    series_name: str | None = None,
) -> WorkIdentityDecision:
    """Resolve a work key without accepting database IDs or volume metadata."""

    normalized_isbn = re.sub(r"[^0-9Xx]", "", str(isbn or "")).upper()
    if _valid_isbn(normalized_isbn):
        return WorkIdentityDecision(f"isbn:{normalized_isbn}", "ISBN")

    normalized_identifier = _usable_identifier(identifier)
    if normalized_identifier is not None:
        return WorkIdentityDecision(
            f"identifier:{normalize_identity_part(normalized_identifier)}",
            "IDENTIFIER",
        )

    normalized_series = normalize_identity_part(series_name or "")
    if normalized_series:
        normalized_author = normalize_identity_part(author or UNKNOWN_AUTHOR)
        return WorkIdentityDecision(
            f"series:{normalized_series}:{normalized_author}",
            "SERIES_AUTHOR",
        )

    return WorkIdentityDecision(
        f"{normalize_identity_part(title)}:"
        f"{normalize_identity_part(author or UNKNOWN_AUTHOR)}",
        "TITLE_AUTHOR",
    )


def _usable_identifier(identifier: str | None) -> str | None:
    value = str(identifier or "").strip()
    lowered = value.lower()
    if not value or lowered.startswith("urn:uuid:"):
        return None
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        lowered,
    ):
        return None
    return value


def _valid_isbn(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        total = sum(
            int(character) * (1 if index % 2 == 0 else 3)
            for index, character in enumerate(value[:12])
        )
        return (10 - total % 10) % 10 == int(value[-1])
    if len(value) == 10 and re.fullmatch(r"[0-9]{9}[0-9X]", value):
        total = sum(
            (10 - index) * (10 if character == "X" else int(character))
            for index, character in enumerate(value)
        )
        return total % 11 == 0
    return False
