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
    requires_full_hash: bool
    preparation: PublicationPreparation = PublicationPreparation.READY


_FORMAT_CAPABILITIES = {
    capability.source_format: capability
    for capability in (
        MediaFormatCapability("EPUB", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("MOBI", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("AZW", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("AZW3", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("PRC", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("TXT", ReaderType.REFLOWABLE, True),
        MediaFormatCapability("CBZ", ReaderType.COMIC, True),
        MediaFormatCapability("PDF", ReaderType.PDF, True),
        MediaFormatCapability("AUDIO", ReaderType.AUDIO, False),
        MediaFormatCapability("AUDIOBOOK", ReaderType.AUDIO, False),
        MediaFormatCapability("M4B", ReaderType.AUDIO, False),
        MediaFormatCapability("M4A", ReaderType.AUDIO, False),
        MediaFormatCapability("MP3", ReaderType.AUDIO, False),
    )
}
_KINDLE_SEND = frozenset({"EPUB", "PDF"})


def capability_for_format(volume_format: str) -> MediaFormatCapability | None:
    """Return the single authoritative Reader capability for a stored format."""

    return _FORMAT_CAPABILITIES.get(volume_format.strip().upper())


def reader_type_for_format(volume_format: str) -> ReaderType | None:
    capability = capability_for_format(volume_format)
    return capability.reader_type if capability is not None else None


def kindle_send_available_for_format(volume_format: str) -> bool:
    return volume_format.strip().upper() in _KINDLE_SEND
