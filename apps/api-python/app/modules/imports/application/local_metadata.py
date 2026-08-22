"""Pure field-by-field resolution for local publication metadata."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, cast

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
    validate_local_metadata_priority,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import finalize_volume_title


@dataclass(frozen=True, slots=True)
class LocalCoverPayload:
    content: bytes


@dataclass(frozen=True, slots=True)
class LocalMetadataCandidate:
    source: LocalMetadataSource
    metadata: PublicationMetadata
    cover: LocalCoverPayload | None = None


@dataclass(frozen=True, slots=True)
class ResolvedLocalMetadata:
    metadata: PublicationMetadata
    cover: LocalCoverPayload | None
    field_sources: tuple[tuple[str, LocalMetadataSource | Literal["REQUESTED"]], ...]
    source_order: tuple[LocalMetadataSource, ...]


def resolve_local_metadata(
    candidates: tuple[LocalMetadataCandidate, ...],
    source_order: tuple[LocalMetadataSource, ...] = DEFAULT_LOCAL_METADATA_PRIORITY,
) -> ResolvedLocalMetadata:
    order = validate_local_metadata_priority(source_order)
    by_source = {candidate.source: candidate for candidate in candidates}
    values: dict[str, object] = {}
    sources: dict[str, LocalMetadataSource | Literal["REQUESTED"]] = {}
    fields = (
        "title",
        "volume_title",
        "authors",
        "narrators",
        "abridged",
        "description",
        "subjects",
        "series_name",
        "series_index",
        "volume_index",
        "language",
        "publisher",
        "published_at",
        "identifier",
        "isbn",
        "unparsed_values",
    )
    for field in fields:
        for source in order:
            candidate = by_source.get(source)
            value = getattr(candidate.metadata, field) if candidate else None
            if _valid_field_value(field, value):
                values[field] = value
                sources[_public_field_name(field)] = source
                break

    cover: LocalCoverPayload | None = None
    for source in order:
        candidate = by_source.get(source)
        if candidate is not None and candidate.cover is not None:
            cover = candidate.cover
            sources["cover"] = source
            break

    metadata = PublicationMetadata(
        title=cast(str | None, values.get("title")),
        volume_title=cast(str | None, values.get("volume_title")),
        authors=cast(tuple[str, ...], values.get("authors", ())),
        narrators=cast(tuple[str, ...], values.get("narrators", ())),
        abridged=cast(bool | None, values.get("abridged")),
        description=cast(str | None, values.get("description")),
        subjects=cast(tuple[str, ...], values.get("subjects", ())),
        series_name=cast(str | None, values.get("series_name")),
        series_index=cast(float | None, values.get("series_index")),
        volume_index=cast(float | None, values.get("volume_index")),
        language=cast(str | None, values.get("language")),
        publisher=cast(str | None, values.get("publisher")),
        published_at=cast(str | None, values.get("published_at")),
        identifier=cast(str | None, values.get("identifier")),
        isbn=cast(str | None, values.get("isbn")),
        unparsed_values=cast(
            tuple[tuple[str, str], ...], values.get("unparsed_values", ())
        ),
    )
    metadata = replace(
        metadata,
        volume_title=finalize_volume_title(
            metadata.title, metadata.volume_title, metadata.volume_index
        ),
    )
    return ResolvedLocalMetadata(
        metadata=metadata,
        cover=cover,
        field_sources=tuple(sources.items()),
        source_order=order,
    )


def _valid_field_value(field: str, value: object) -> bool:
    if value in (None, "", (), []):
        return False
    if field in {"series_index", "volume_index"}:
        return (
            isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) >= 0
        )
    return True


def _public_field_name(field: str) -> str:
    return {
        "authors": "author",
        "narrators": "narrator",
        "volume_title": "volumeTitle",
        "subjects": "tags",
        "series_name": "seriesName",
        "series_index": "seriesIndex",
        "volume_index": "volumeIndex",
        "published_at": "publishedAt",
        "unparsed_values": "unparsed",
    }.get(field, field)


__all__ = [
    "LocalCoverPayload",
    "LocalMetadataCandidate",
    "ResolvedLocalMetadata",
    "resolve_local_metadata",
]
