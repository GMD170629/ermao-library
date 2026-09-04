"""Stable reader capability contracts."""

from __future__ import annotations

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderExternalProgressDto,
)
from app.modules.reader.application.resource_reader import (
    ReaderProgressDateConflict,
    ReaderResourceFormatUnsupported,
    ReaderResourceNotFound,
    ResourceReaderService,
    SaveExternalProgressCommand,
)
from app.modules.reader.application.v5_library_queries import (
    ReaderV5LibraryPresentationQueryPort,
    ReaderV5PresentationView,
    ReaderV5StatusView,
)
from app.modules.reader.domain.progress import (
    normalize_reader_href,
    number_or_none,
    progress_location,
    progress_navigation,
    progress_percent_with_navigation,
    raw_progress_percent,
    reader_unit_index,
    reader_unit_index_at_position,
)
from app.modules.reader.domain.resource_progress import (
    ResourceReadingState,
    choose_continue_resource_id,
    completed_for_available_resources,
)

__all__ = [
    "ReaderAccessScope",
    "ReaderExternalProgressDto",
    "ReaderProgressDateConflict",
    "ReaderResourceFormatUnsupported",
    "ReaderResourceNotFound",
    "ReaderV5LibraryPresentationQueryPort",
    "ReaderV5PresentationView",
    "ReaderV5StatusView",
    "ResourceReaderService",
    "ResourceReadingState",
    "SaveExternalProgressCommand",
    "choose_continue_resource_id",
    "completed_for_available_resources",
    "normalize_reader_href",
    "number_or_none",
    "progress_location",
    "progress_navigation",
    "progress_percent_with_navigation",
    "raw_progress_percent",
    "reader_unit_index",
    "reader_unit_index_at_position",
]
