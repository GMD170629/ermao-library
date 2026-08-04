"""Reader capabilities derived from a concrete volume format."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts.media_capabilities import ReaderType, reader_type_for_format


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
    return reader_type_for_format(volume_format)


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
