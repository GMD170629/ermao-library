"""Pure policies for morphology-specific exact Reader locations."""

from __future__ import annotations

from app.modules.reader.application.dto import (
    ExactReaderLocationKind,
    ReaderAudioExactLocationDto,
    ReaderComicExactLocationDto,
    ReaderExactLocationDto,
    ReaderPdfExactLocationDto,
    ReaderReflowableExactLocationDto,
)


def exact_location_kind(location: ReaderExactLocationDto) -> ExactReaderLocationKind:
    if isinstance(location, ReaderReflowableExactLocationDto):
        return "reflowable"
    if isinstance(location, ReaderPdfExactLocationDto):
        return "pdf"
    if isinstance(location, ReaderComicExactLocationDto):
        return "comic"
    if isinstance(location, ReaderAudioExactLocationDto):
        return "audio"
    raise TypeError("Unsupported exact Reader location")
