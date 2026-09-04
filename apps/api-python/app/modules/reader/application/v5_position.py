"""Pure serialization rules for the Reader v5 position report.

The locator is treated as an opaque JSON object.  The only fields the service
projects are the six client-owned presentation values.  Keeping this encoder
in the application layer gives the ORM adapter one authoritative representation
for ``presentationJson`` and its indexed projection columns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from app.modules.reader.application.v5_dto import (
    ReaderV5ChapterDto,
    ReaderV5PageDto,
    ReaderV5PlaybackDto,
    ReaderV5PositionDto,
    ReaderV5PresentationDto,
)
from app.modules.reader.application.v5_locator import OpaqueLocator


@dataclass(frozen=True, slots=True)
class ReaderV5StoredPosition:
    locator: OpaqueLocator
    presentation_json: str
    presentation: ReaderV5PresentationDto


def _compact_json(value: object, *, sort_keys: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        sort_keys=sort_keys,
    )


def _chapter_json(value: ReaderV5ChapterDto | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"href": value.href, "title": value.title, "index": value.index}


def _page_json(value: ReaderV5PageDto | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"number": value.number, "total": value.total}


def _playback_json(value: ReaderV5PlaybackDto | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "positionMillis": value.position_millis,
        "durationMillis": value.duration_millis,
    }


def presentation_json(value: ReaderV5PresentationDto) -> dict[str, object]:
    """Return the complete wire-shaped presentation projection.

    All six keys are emitted, including explicit nulls.  This is deliberately
    the only place where DTO fields are converted to the stored wire shape.
    """

    return {
        "displayPercent": value.display_percent,
        "totalProgression": value.total_progression,
        "currentHref": value.current_href,
        "chapter": _chapter_json(value.chapter),
        "page": _page_json(value.page),
        "playback": _playback_json(value.playback),
    }


def serialize_position(position: ReaderV5PositionDto) -> ReaderV5StoredPosition:
    """Encode an opaque locator and its client presentation exactly once."""

    presentation = presentation_json(position.presentation)
    presentation_json_text = _compact_json(presentation)
    return ReaderV5StoredPosition(
        locator=position.locator,
        presentation_json=presentation_json_text,
        presentation=position.presentation,
    )


def payload_hash(
    *,
    client_id: str,
    mutation_id: str,
    captured_at_epoch_millis: int,
    position: ReaderV5PositionDto,
) -> str:
    """Hash a normalized request payload for mutation-id reuse detection."""

    stored = serialize_position(position)
    return payload_hash_for_stored(
        client_id=client_id,
        mutation_id=mutation_id,
        captured_at_epoch_millis=captured_at_epoch_millis,
        stored_position=stored,
    )


def payload_hash_for_stored(
    *,
    client_id: str,
    mutation_id: str,
    captured_at_epoch_millis: int,
    stored_position: ReaderV5StoredPosition,
) -> str:
    """Hash a request after its single authoritative position serialization."""

    request_value = {
        "schemaVersion": 5,
        "clientId": client_id,
        "mutationId": mutation_id,
        "capturedAtEpochMillis": captured_at_epoch_millis,
        "position": {
            "locatorDigest": stored_position.locator.digest,
            "presentation": json.loads(stored_position.presentation_json),
        },
    }
    canonical_request = _compact_json(request_value, sort_keys=True)
    return sha256(canonical_request.encode("utf-8")).hexdigest()
