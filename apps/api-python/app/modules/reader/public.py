"""Stable reader capability contracts."""

from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderExternalProgressDto,
)
from app.modules.reader.application.volume_reader import (
    ReaderProgressDateConflict,
    ReaderVolumeFormatUnsupported,
    ReaderVolumeNotFound,
    SaveExternalProgressCommand,
    VolumeReaderService,
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
from app.modules.reader.domain.volume_progress import (
    MediaKind,
    VolumeReadingState,
    choose_continue_volume_id,
    completed_for_available_volumes,
)

__all__ = [
    "MediaKind",
    "ReaderAccessScope",
    "ReaderExternalProgressDto",
    "ReaderProgressDateConflict",
    "ReaderVolumeFormatUnsupported",
    "ReaderVolumeNotFound",
    "SaveExternalProgressCommand",
    "VolumeReaderService",
    "VolumeReadingState",
    "choose_continue_volume_id",
    "completed_for_available_volumes",
    "normalize_reader_href",
    "number_or_none",
    "progress_location",
    "progress_navigation",
    "progress_percent_with_navigation",
    "raw_progress_percent",
    "reader_unit_index",
    "reader_unit_index_at_position",
]
