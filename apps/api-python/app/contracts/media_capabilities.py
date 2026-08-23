"""Stable format-driven media capabilities shared across capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
        MediaFormatCapability("CBZ", ReaderType.COMIC),
        MediaFormatCapability("ZIP", ReaderType.COMIC),
        MediaFormatCapability("CBR", ReaderType.COMIC),
        MediaFormatCapability("RAR", ReaderType.COMIC),
        MediaFormatCapability("PDF", ReaderType.PDF),
        MediaFormatCapability("AUDIO", ReaderType.AUDIO),
        MediaFormatCapability("AUDIOBOOK", ReaderType.AUDIO),
        MediaFormatCapability("M4B", ReaderType.AUDIO),
        MediaFormatCapability("M4A", ReaderType.AUDIO),
        MediaFormatCapability("MP3", ReaderType.AUDIO),
    )
}
_KINDLE_SEND = frozenset({"EPUB", "PDF"})


def capability_for_format(resource_format: str) -> MediaFormatCapability | None:
    """Return the single authoritative Reader capability for a stored format."""

    return _FORMAT_CAPABILITIES.get(resource_format.strip().upper())


def reader_type_for_format(resource_format: str) -> ReaderType | None:
    capability = capability_for_format(resource_format)
    return capability.reader_type if capability is not None else None


def kindle_send_available_for_format(resource_format: str) -> bool:
    return resource_format.strip().upper() in _KINDLE_SEND
