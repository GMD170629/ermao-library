"""Reader capabilities derived from a concrete volume format."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReaderType(StrEnum):
    REFLOWABLE = "reflowable"
    COMIC = "comic"
    PDF = "pdf"
    AUDIO = "audio"


_REFLOWABLE = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT"})
_COMIC = frozenset({"COMIC", "CBZ", "ZIP"})
_AUDIO = frozenset({"AUDIO", "AUDIOBOOK", "M4B", "M4A", "MP3"})


@dataclass(frozen=True, slots=True)
class ReaderCapabilities:
    can_go_next: bool
    can_go_previous: bool
    can_jump_to_progress: bool
    can_jump_to_href: bool
    can_jump_to_index: bool
    can_zoom: bool
    can_select_text: bool
    supports_pagination: bool
    supports_scrolling: bool
    supports_spreads: bool


def reader_type_for_volume_format(volume_format: str) -> ReaderType | None:
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


def capabilities_for_reader_type(reader_type: ReaderType) -> ReaderCapabilities:
    reflowable = reader_type == ReaderType.REFLOWABLE
    comic_or_pdf = reader_type in {ReaderType.COMIC, ReaderType.PDF}
    return ReaderCapabilities(
        can_go_next=True,
        can_go_previous=True,
        can_jump_to_progress=True,
        can_jump_to_href=reflowable,
        can_jump_to_index=True,
        can_zoom=comic_or_pdf,
        can_select_text=reflowable or reader_type == ReaderType.PDF,
        supports_pagination=reader_type != ReaderType.AUDIO,
        supports_scrolling=reflowable or comic_or_pdf,
        supports_spreads=reflowable or reader_type == ReaderType.COMIC,
    )
