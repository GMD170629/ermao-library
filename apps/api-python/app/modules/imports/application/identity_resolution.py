"""Pure multi-source identity arbitration for imported publications."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from app.contracts.local_metadata import LocalMetadataSource
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    IdentityEvidenceDTO,
    IdentitySource,
)
from app.modules.imports.application.local_metadata import (
    LocalMetadataCandidate,
    ResolvedLocalMetadata,
    resolve_local_metadata,
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


def resolve_import_metadata(
    path_identity: BookIdentityDTO,
    *,
    embedded: PublicationMetadata | None,
    sidecar: PublicationMetadata | None,
    source_order: tuple[LocalMetadataSource, ...],
    path_metadata: PublicationMetadata | None = None,
    path_publication_title: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> tuple[BookIdentityDTO, ResolvedLocalMetadata]:
    """Resolve one complete local snapshot before database identity decisions."""

    resolved_path_metadata = path_metadata or _path_metadata_from_identity(
        path_identity,
        path_publication_title=path_publication_title,
    )
    candidates = [
        LocalMetadataCandidate(
            source="PATH",
            metadata=resolved_path_metadata,
        )
    ]
    if embedded is not None:
        candidates.append(
            LocalMetadataCandidate(
                source="EMBEDDED", metadata=_normalize_source_metadata(embedded)
            )
        )
    if sidecar is not None:
        candidates.append(
            LocalMetadataCandidate(
                source="SIDECAR_OPF", metadata=_normalize_source_metadata(sidecar)
            )
        )
    resolved = resolve_local_metadata(
        tuple(candidates),
        source_order,
        requested_title=requested_title,
        requested_author=requested_author,
    )
    publication = resolved.metadata
    title = publication.title or publication.series_name or path_identity.title
    author = publication.author or UNKNOWN_AUTHOR
    selected_source = (
        resolved.source_for("title") or resolved.source_for("author") or "PATH"
    )
    source_mapping: dict[str, IdentitySource] = {
        "SIDECAR_OPF": "sidecar_opf",
        "EMBEDDED": "epub_opf",
        "PATH": path_identity.source,
        "REQUESTED": "requested",
    }
    identity_source = source_mapping[selected_source]
    identity = replace(
        path_identity,
        title=title,
        author=author,
        volume_index=publication.volume_index,
        source=identity_source,
        confidence=1.0
        if selected_source in {"SIDECAR_OPF", "REQUESTED"}
        else path_identity.confidence,
        selection_reason="resolved_local_metadata",
    )
    return identity, resolved


def _path_metadata_from_identity(
    path_identity: BookIdentityDTO,
    *,
    path_publication_title: str | None,
) -> PublicationMetadata:
    """Build filename metadata without inferring structural ownership."""

    resolved_path_title = path_publication_title or path_identity.title
    path_author = _valid_author(path_identity.author)
    if path_identity.volume_index is not None and _looks_like_volume_label(path_author):
        path_author = None
    path_titles = titles_from_local_source(
        resolved_path_title,
        volume_index=path_identity.volume_index,
    )
    return PublicationMetadata(
        title=path_titles.work_title,
        volume_title=path_titles.volume_title,
        authors=(path_author,) if path_author else (),
        volume_index=path_titles.volume_index,
    )


def _normalize_source_metadata(
    metadata: PublicationMetadata,
) -> PublicationMetadata:
    """Normalize compatibility candidates before any cross-source comparison."""

    if metadata.volume_title is not None or metadata.title is None:
        return metadata
    titles = titles_from_local_source(
        metadata.title,
        series_name=metadata.series_name,
        volume_index=metadata.volume_index,
    )
    return replace(
        metadata,
        title=titles.work_title,
        volume_title=titles.volume_title,
        volume_index=titles.volume_index,
    )


def _looks_like_volume_label(value: str | None) -> bool:
    if value is None:
        return False
    return bool(
        re.fullmatch(
            r"(?:vol[._\s-]*\d+(?:\.\d+)?|"
            r"\u7b2c?\s*\d+(?:\.\d+)?"
            r"(?:\s*[-~\uff5e\u2014]\s*\d+(?:\.\d+)?)?"
            r"\s*[\u8bdd\u7ae0\u5377\u518c\u96c6]?)",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


def apply_requested_identity(
    path_identity: BookIdentityDTO,
    *,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> BookIdentityDTO:
    """Apply only explicit user intent before format metadata is available."""

    path_evidence = IdentityEvidenceDTO(
        source=path_identity.source,
        title=_clean_value(path_identity.title),
        author=_clean_value(path_identity.author),
        confidence=_confidence(path_identity.confidence),
    )
    evidence = _merge_evidence(path_identity.evidence, (path_evidence,))

    requested_title_value = _valid_title(requested_title)
    requested_author_value = _valid_author(requested_author)
    if requested_title_value is None and requested_author_value is None:
        return replace(path_identity, evidence=evidence)
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

    return replace(
        path_identity,
        title=requested_title_value or path_identity.title,
        author=requested_author_value or path_identity.author,
        source="requested",
        confidence=1.0,
        selection_reason="explicit_user_fields",
        evidence=evidence,
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
