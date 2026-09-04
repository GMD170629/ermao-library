from __future__ import annotations

import json
import math

import pytest

from app.modules.reader.application.v5_dto import (
    ReaderV5ChapterDto,
    ReaderV5PageDto,
    ReaderV5PlaybackDto,
    ReaderV5PositionDto,
    ReaderV5PresentationDto,
)
from app.modules.reader.application.v5_locator import (
    MAX_OPAQUE_LOCATOR_BYTES,
    OpaqueLocator,
)
from app.modules.reader.application.v5_position import (
    payload_hash_for_stored,
    serialize_position,
)


def _presentation() -> ReaderV5PresentationDto:
    return ReaderV5PresentationDto(
        display_percent=42.5,
        total_progression=0.425,
        current_href="Text/chapter.xhtml",
        chapter=ReaderV5ChapterDto(
            href="Text/chapter.xhtml",
            title="Chapter",
            index=2,
        ),
        page=ReaderV5PageDto(number=3, total=10),
        playback=ReaderV5PlaybackDto(position_millis=100, duration_millis=None),
    )


def test_opaque_locator_canonicalizes_without_exposing_members() -> None:
    locator = OpaqueLocator.from_object(
        {"z": {"empty": ""}, "a": None, "highlight": ""}
    )

    assert locator.serialized == '{"a":null,"highlight":"","z":{"empty":""}}'
    assert locator.size_bytes == len(locator.serialized.encode("utf-8"))
    assert len(locator.digest) == 64
    assert not hasattr(locator, "value")


def test_position_serialization_round_trips_complete_presentation() -> None:
    position = ReaderV5PositionDto(
        locator=OpaqueLocator.from_object({"unknown": None, "text": {"highlight": ""}}),
        presentation=_presentation(),
    )

    stored = serialize_position(position)
    presentation = json.loads(stored.presentation_json)

    assert presentation == {
        "displayPercent": 42.5,
        "totalProgression": 0.425,
        "currentHref": "Text/chapter.xhtml",
        "chapter": {"href": "Text/chapter.xhtml", "title": "Chapter", "index": 2},
        "page": {"number": 3, "total": 10},
        "playback": {"positionMillis": 100, "durationMillis": None},
    }
    assert set(presentation) == {
        "displayPercent",
        "totalProgression",
        "currentHref",
        "chapter",
        "page",
        "playback",
    }


def test_payload_hash_does_not_apply_locator_limit_to_request_envelope() -> None:
    # ``{"x":""}`` has eight UTF-8 bytes; this fills the Locator budget exactly.
    locator = OpaqueLocator.from_object({"x": "a" * (MAX_OPAQUE_LOCATOR_BYTES - 8)})
    assert locator.size_bytes == MAX_OPAQUE_LOCATOR_BYTES
    stored = serialize_position(
        ReaderV5PositionDto(locator=locator, presentation=_presentation())
    )

    digest = payload_hash_for_stored(
        client_id="test-client",
        mutation_id="00000000-0000-4000-8000-000000000001",
        captured_at_epoch_millis=0,
        stored_position=stored,
    )

    assert len(digest) == 64


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_presentation_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        ReaderV5PresentationDto(
            display_percent=value,
            total_progression=0.5,
            current_href=None,
            chapter=None,
            page=None,
            playback=None,
        )
    with pytest.raises(ValueError):
        ReaderV5PresentationDto(
            display_percent=50,
            total_progression=value,
            current_href=None,
            chapter=None,
            page=None,
            playback=None,
        )


def test_nested_presentation_boundaries_are_validated_in_application_dtos() -> None:
    with pytest.raises(ValueError):
        ReaderV5ChapterDto(href=None, title=None, index=-1)
    with pytest.raises(ValueError):
        ReaderV5PageDto(number=0, total=None)
    with pytest.raises(ValueError):
        ReaderV5PlaybackDto(position_millis=-1, duration_millis=None)
