"""Stable format-driven media capabilities shared across capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


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


_FORMAT_CAPABILITIES = {
    capability.source_format: capability
    for capability in (
        MediaFormatCapability("EPUB", ReaderType.REFLOWABLE),
        MediaFormatCapability("MOBI", ReaderType.REFLOWABLE),
        MediaFormatCapability("AZW", ReaderType.REFLOWABLE),
        MediaFormatCapability("AZW3", ReaderType.REFLOWABLE),
        MediaFormatCapability("PRC", ReaderType.REFLOWABLE),
        MediaFormatCapability("TXT", ReaderType.REFLOWABLE),
        MediaFormatCapability("FB2", ReaderType.REFLOWABLE),
        MediaFormatCapability("KINDLE", ReaderType.REFLOWABLE),
        MediaFormatCapability("CBZ", ReaderType.COMIC),
        MediaFormatCapability("ZIP", ReaderType.COMIC),
        MediaFormatCapability("CBR", ReaderType.COMIC),
        MediaFormatCapability("RAR", ReaderType.COMIC),
        MediaFormatCapability("IMAGE_DIR", ReaderType.COMIC),
        MediaFormatCapability("PDF", ReaderType.PDF),
        MediaFormatCapability("AUDIO", ReaderType.AUDIO),
        MediaFormatCapability("AUDIOBOOK", ReaderType.AUDIO),
        MediaFormatCapability("AUDIOBOOK_DIR", ReaderType.AUDIO),
        MediaFormatCapability("M4B", ReaderType.AUDIO),
        MediaFormatCapability("M4A", ReaderType.AUDIO),
        MediaFormatCapability("MP3", ReaderType.AUDIO),
    )
}
_KINDLE_SEND = frozenset({"EPUB", "PDF"})
_GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
_CANONICAL_PUBLICATION_MIME_TYPES: dict[str, str] = {
    "EPUB": "application/epub+zip",
    "MOBI": "application/x-mobipocket-ebook",
    "AZW": "application/vnd.amazon.ebook",
    "AZW3": "application/vnd.amazon.ebook",
    "PRC": "application/x-mobipocket-ebook",
    "KINDLE": "application/x-mobipocket-ebook",
    "TXT": "text/plain",
    "FB2": "application/x-fictionbook+xml",
    "CBZ": "application/vnd.comicbook+zip",
    "ZIP": "application/zip",
    "CBR": "application/vnd.comicbook-rar",
    "RAR": "application/vnd.rar",
    "PDF": "application/pdf",
    "M4B": "audio/mp4",
    "M4A": "audio/mp4",
    "MP3": "audio/mpeg",
}
_IMAGE_MIME_TYPES_BY_SUFFIX: dict[str, str] = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_KINDLE_SOURCE_FORMATS_BY_SUFFIX: dict[str, str] = {
    ".azw": "AZW",
    ".azw3": "AZW3",
    ".mobi": "MOBI",
    ".prc": "PRC",
}


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

    return _CANONICAL_PUBLICATION_MIME_TYPES.get(resource_format.strip().upper())


def exact_source_format(*, resource_format: str, filename: str) -> str:
    """Map a stored resource family back to its original publication format.

    The catalog intentionally groups MOBI-family resources as ``KINDLE``. Reader
    and media delivery still need the exact original format, which is stable in
    the source-node filename and does not require rewriting existing rows.
    """

    normalized_format = resource_format.strip().upper()
    if normalized_format != "KINDLE":
        return normalized_format
    suffix = PurePosixPath(filename).suffix.lower()
    return _KINDLE_SOURCE_FORMATS_BY_SUFFIX.get(suffix, normalized_format)


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
    normalized_format = exact_source_format(
        resource_format=resource_format,
        filename=filename,
    )
    if normalized_role == "PAGE" or normalized_format == "IMAGE_DIR":
        suffix = PurePosixPath(filename).suffix.lower()
        image_mime_type = _IMAGE_MIME_TYPES_BY_SUFFIX.get(suffix)
        if image_mime_type is not None:
            return image_mime_type

    if normalized_role == "PRIMARY":
        canonical = canonical_publication_mime_type(normalized_format)
        if canonical is not None:
            return canonical

    normalized_stored = (stored_mime_type or "").strip().lower().split(";", 1)[0]
    if normalized_stored not in _GENERIC_MIME_TYPES:
        return normalized_stored

    return "application/octet-stream"
