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
class LocalMetadataCandidate:
    source: LocalMetadataSource
    metadata: PublicationMetadata
    evidence: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedLocalMetadata:
    metadata: PublicationMetadata
    field_sources: tuple[tuple[str, LocalMetadataSource | Literal["REQUESTED"]], ...]
    source_order: tuple[LocalMetadataSource, ...]
    warnings: tuple[str, ...] = ()

    def source_for(self, field: str) -> str | None:
        return dict(self.field_sources).get(field)


def resolve_local_metadata(
    candidates: tuple[LocalMetadataCandidate, ...],
    source_order: tuple[LocalMetadataSource, ...] = DEFAULT_LOCAL_METADATA_PRIORITY,
    *,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> ResolvedLocalMetadata:
    order = validate_local_metadata_priority(source_order)
    by_source = {candidate.source: candidate for candidate in candidates}
    values: dict[str, object] = {}
    sources: dict[str, LocalMetadataSource | Literal["REQUESTED"]] = {}
    fields = (
        "title",
        "volume_title",
        "authors",
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
        "cover_href",
        "unparsed_values",
    )
    for field in fields:
        for source in order:
            candidate = by_source.get(source)
            value = (
                getattr(candidate.metadata, field) if candidate is not None else None
            )
            if _valid_field_value(field, value):
                values[field] = value
                sources[_public_field_name(field)] = source
                break

    title = _clean(requested_title)
    author = _clean(requested_author)
    if title is not None:
        values["title"] = title
        sources["title"] = "REQUESTED"
    if author is not None:
        values["authors"] = (author,)
        sources["author"] = "REQUESTED"

    metadata = PublicationMetadata(
        title=cast(str | None, values.get("title")),
        volume_title=cast(str | None, values.get("volume_title")),
        authors=cast(tuple[str, ...], values.get("authors", ())),
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
        cover_href=cast(str | None, values.get("cover_href")),
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
    if metadata.volume_title is not None and "volumeTitle" not in sources:
        derived_source = sources.get("title") or sources.get("volumeIndex")
        if derived_source is not None:
            sources["volumeTitle"] = derived_source
    warnings: list[str] = []
    for source in order:
        candidate = by_source.get(source)
        if candidate is not None:
            warnings.extend(candidate.warnings)
    return ResolvedLocalMetadata(
        metadata=metadata,
        field_sources=tuple(sources.items()),
        source_order=order,
        warnings=tuple(warnings),
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
        "volume_title": "volumeTitle",
        "subjects": "tags",
        "series_name": "seriesName",
        "series_index": "seriesIndex",
        "volume_index": "volumeIndex",
        "published_at": "publishedAt",
        "cover_href": "cover",
        "unparsed_values": "unparsed",
    }.get(field, field)


def _clean(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


__all__ = [
    "DEFAULT_LOCAL_METADATA_PRIORITY",
    "LocalMetadataCandidate",
    "LocalMetadataSource",
    "ResolvedLocalMetadata",
    "resolve_local_metadata",
    "validate_local_metadata_priority",
]
