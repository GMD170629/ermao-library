"""Stable format-driven media capabilities shared across capabilities."""

from __future__ import annotations

from enum import StrEnum


class ReaderType(StrEnum):
    REFLOWABLE = "reflowable"
    COMIC = "comic"
    PDF = "pdf"
    AUDIO = "audio"


_REFLOWABLE = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT"})
_COMIC = frozenset({"COMIC", "CBR", "CBZ", "RAR", "ZIP"})
_AUDIO = frozenset({"AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3"})
_KINDLE_SEND = frozenset({"EPUB", "PDF"})


def reader_type_for_format(volume_format: str) -> ReaderType | None:
    normalized = volume_format.strip().upper()
    if normalized in _REFLOWABLE:
        return ReaderType.REFLOWABLE
    if normalized == "PDF":
        return ReaderType.PDF
    if normalized in _COMIC:
        return ReaderType.COMIC
    if normalized in _AUDIO:
        return ReaderType.AUDIO
    return None


def kindle_send_available_for_format(volume_format: str) -> bool:
    return volume_format.strip().upper() in _KINDLE_SEND
