"""Stable format-driven media capabilities shared across capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_FORMATS,
    ReaderSafetyMorphology,
    reader_safety_comic_page_mime_type,
    reader_safety_format_policy,
)


class ReaderType(StrEnum):
    REFLOWABLE = "reflowable"
    COMIC = "comic"
    PDF = "pdf"
    AUDIO = "audio"


class PublicationPreparation(StrEnum):
    READY = "READY"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class MediaFormatCapability:
    source_format: str
    reader_type: ReaderType
    preparation: PublicationPreparation = PublicationPreparation.READY


_READER_TYPE_BY_MORPHOLOGY = {
    ReaderSafetyMorphology.REFLOWABLE: ReaderType.REFLOWABLE,
    ReaderSafetyMorphology.COMIC: ReaderType.COMIC,
    ReaderSafetyMorphology.PDF: ReaderType.PDF,
    ReaderSafetyMorphology.AUDIO: ReaderType.AUDIO,
}
_FORMAT_CAPABILITIES = {
    format_policy.id.value: MediaFormatCapability(
        format_policy.id.value,
        _READER_TYPE_BY_MORPHOLOGY[format_policy.morphology],
    )
    for format_policy in READER_SAFETY_FORMATS.values()
}
_KINDLE_SEND = frozenset({"EPUB", "PDF"})
_GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})


def capability_for_format(resource_format: str) -> MediaFormatCapability | None:
    """Return the single authoritative Reader capability for a stored format."""

    return _FORMAT_CAPABILITIES.get(resource_format.strip().upper())


def reader_type_for_format(resource_format: str) -> ReaderType | None:
    capability = capability_for_format(resource_format)
    return capability.reader_type if capability is not None else None


def require_reader_type_for_format(resource_format: str) -> ReaderType:
    reader_type = reader_type_for_format(resource_format)
    if reader_type is None:
        raise ValueError(f"unsupported resource format: {resource_format}")
    return reader_type


def kindle_send_available_for_format(resource_format: str) -> bool:
    return resource_format.strip().upper() in _KINDLE_SEND


def canonical_publication_mime_type(resource_format: str) -> str | None:
    """Return the canonical MIME for a single original publication artifact.

    Directory-backed publications deliberately return ``None`` because they do not
    have one synthetic downloadable artifact.
    """

    format_policy = reader_safety_format_policy(resource_format)
    return format_policy.canonical_mime_type if format_policy is not None else None


def resolve_asset_mime_type(
    *,
    resource_format: str,
    asset_role: str,
    filename: str,
    stored_mime_type: str | None,
) -> str:
    """Resolve the delivery MIME without mutating persisted rows.

    Original publication and page assets have a format-defined canonical MIME.
    Stored metadata remains a fallback only for formats without such a rule, so
    legacy but overly broad or conflicting values cannot make bootstrap and HTTP
    delivery disagree.
    """

    normalized_role = asset_role.strip().upper()
    normalized_format = resource_format.strip().upper()
    if normalized_role == "PAGE" or normalized_format == "IMAGE_DIR":
        extension = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        return (
            reader_safety_comic_page_mime_type(extension) or "application/octet-stream"
        )

    if normalized_role == "PRIMARY":
        canonical = canonical_publication_mime_type(normalized_format)
        if canonical is not None:
            return canonical

    normalized_stored = (stored_mime_type or "").strip().lower().split(";", 1)[0]
    if normalized_stored not in _GENERIC_MIME_TYPES:
        return normalized_stored

    return "application/octet-stream"
