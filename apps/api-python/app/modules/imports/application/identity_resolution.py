"""Pure multi-source identity arbitration for imported publications."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Literal

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    IdentityEvidenceDTO,
)

UNKNOWN_AUTHOR = "未知作者"
_UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknownauthor",
    "n/a",
    "na",
    "none",
    "未知",
    "未知作者",
    "佚名",
}


@dataclass(frozen=True)
class EmbeddedIdentityMetadata:
    title: str | None
    author: str | None
    source: Literal["epub_opf", "pdf_metadata", "comic_info", "reflowable_metadata"]
    confidence: float


def resolve_import_identity(
    path_identity: BookIdentityDTO,
    *,
    embedded: EmbeddedIdentityMetadata | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> BookIdentityDTO:
    """Choose title and author from explicit, embedded, and path evidence.

    Existing-work and series-volume titles are structural decisions and remain
    path-owned; valid PDF metadata may still fill a placeholder path author. A
    complete, high-confidence path identity also remains authoritative so
    misleading package metadata cannot merge an unrelated book. Otherwise
    valid embedded metadata repairs incomplete or low-confidence filenames.
    Explicit user fields are applied field by field.
    """

    path_evidence = IdentityEvidenceDTO(
        source=path_identity.source,
        title=_clean_value(path_identity.title),
        author=_clean_value(path_identity.author),
        confidence=_confidence(path_identity.confidence),
    )
    evidence = _merge_evidence(path_identity.evidence, (path_evidence,))
    embedded_evidence = _embedded_evidence(embedded)
    if embedded_evidence is not None:
        evidence = _merge_evidence(evidence, (embedded_evidence,))

    requested_title_value = _valid_title(requested_title)
    requested_author_value = _valid_author(requested_author)
    if requested_title_value is not None or requested_author_value is not None:
        evidence = _merge_evidence(
            evidence,
            (
                IdentityEvidenceDTO(
                    source="requested",
                    title=requested_title_value,
                    author=requested_author_value,
                    confidence=1.0,
                ),
            ),
        )

    title = _valid_title(path_identity.title) or _clean_value(path_identity.title)
    author = _valid_author(path_identity.author) or UNKNOWN_AUTHOR
    source = path_identity.source
    confidence = _confidence(path_identity.confidence)
    reason = "path_fallback"

    path_is_structural = (
        path_identity.source == "existing_work"
        or path_identity.volume_index is not None
    )
    path_is_complete = (
        _valid_title(title) is not None and _valid_author(author) is not None
    )
    if path_is_structural:
        reason = (
            "existing_work_path"
            if path_identity.source == "existing_work"
            else "series_volume_path"
        )
        embedded_author = (
            _valid_author(embedded_evidence.author)
            if embedded_evidence is not None
            else None
        )
        if (
            embedded_evidence is not None
            and embedded_evidence.source == "pdf_metadata"
            and _valid_author(author) is None
            and embedded_author is not None
        ):
            author = embedded_author
            source = embedded_evidence.source
            confidence = embedded_evidence.confidence
            reason = "embedded_author_over_incomplete_path"
    elif path_is_complete and confidence >= 0.9:
        reason = "complete_high_confidence_path"
    elif embedded_evidence is not None:
        embedded_title = _valid_title(embedded_evidence.title)
        embedded_author = _valid_author(embedded_evidence.author)
        used_embedded = False
        if embedded_title is not None:
            title = embedded_title
            used_embedded = True
        if embedded_author is not None:
            author = embedded_author
            used_embedded = True
        if used_embedded:
            source = embedded_evidence.source
            confidence = embedded_evidence.confidence
            reason = "embedded_metadata_over_incomplete_path"

    if not path_is_structural and (
        requested_title_value is not None or requested_author_value is not None
    ):
        if requested_title_value is not None:
            title = requested_title_value
        if requested_author_value is not None:
            author = requested_author_value
        source = "requested"
        confidence = 1.0
        reason = "explicit_user_fields"

    return replace(
        path_identity,
        title=title or path_identity.title,
        author=author or UNKNOWN_AUTHOR,
        source=source,
        confidence=confidence,
        selection_reason=reason,
        evidence=evidence,
    )


def _embedded_evidence(
    embedded: EmbeddedIdentityMetadata | None,
) -> IdentityEvidenceDTO | None:
    if embedded is None:
        return None
    title = _valid_title(embedded.title)
    author = _valid_author(embedded.author)
    if title is None and author is None:
        return None
    return IdentityEvidenceDTO(
        source=embedded.source,
        title=title,
        author=author,
        confidence=_confidence(embedded.confidence),
    )


def _merge_evidence(
    current: tuple[IdentityEvidenceDTO, ...],
    additions: tuple[IdentityEvidenceDTO, ...],
) -> tuple[IdentityEvidenceDTO, ...]:
    merged = list(current)
    keys = {(item.source, item.title, item.author, item.confidence) for item in current}
    for item in additions:
        key = (item.source, item.title, item.author, item.confidence)
        if key not in keys:
            merged.append(item)
            keys.add(key)
    return tuple(merged)


def _valid_title(value: object) -> str | None:
    cleaned = _clean_value(value)
    return cleaned if _identity_key(cleaned) not in _UNKNOWN_VALUES else None


def _valid_author(value: object) -> str | None:
    cleaned = _clean_value(value)
    return cleaned if _identity_key(cleaned) not in _UNKNOWN_VALUES else None


def _clean_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _identity_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s._\-()/（）]+", "", normalized)


def _confidence(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
