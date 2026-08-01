"""Stable reader capability contracts."""

from app.modules.reader.application.content_fingerprint import build_content_fingerprint
from app.modules.reader.application.progress import (
    ClaimClientSequence,
    ClaimClientSequenceCommand,
    ReaderProgressCursorPort,
)
from app.modules.reader.domain.progress import (
    choose_continue_volume,
    continue_progress_for_edition,
    display_progress_percent,
    empty_progress_for_volume,
    latest_progress,
    normalize_reader_href,
    number_or_none,
    progress_chapter_label,
    progress_extra,
    progress_for_volume,
    progress_navigation,
    progress_percent_with_navigation,
    raw_progress_percent,
    reader_unit_index,
)

__all__ = [
    "ClaimClientSequence",
    "ClaimClientSequenceCommand",
    "ReaderProgressCursorPort",
    "build_content_fingerprint",
    "choose_continue_volume",
    "continue_progress_for_edition",
    "display_progress_percent",
    "empty_progress_for_volume",
    "latest_progress",
    "normalize_reader_href",
    "number_or_none",
    "progress_chapter_label",
    "progress_extra",
    "progress_for_volume",
    "progress_navigation",
    "progress_percent_with_navigation",
    "raw_progress_percent",
    "reader_unit_index",
]
