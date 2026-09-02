"""Shared local publication metadata contracts and resolution rules.

The imports capability owns format-specific byte inspection (EPUB/PDF/audio and
similar formats).  This module owns the capability-neutral part of that
workflow: turning path, embedded and sidecar observations into candidates and
resolving those candidates using the configured source order.  Keeping that
composition here lets import and synchronous cover regeneration use exactly the
same local-metadata semantics without making metadata depend on an import
adapter or on its concrete audio DTO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol, cast

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataSource,
    validate_local_metadata_priority,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import (
    finalize_volume_title,
    titles_from_local_source,
)

_AUDIOBOOK_DIRECTORY_FORMATS = frozenset({"AUDIOBOOK_DIRECTORY", "AUDIOBOOK_DIR"})
_AUDIO_FORMATS = frozenset(
    {"AUDIO", "AUDIOBOOK", "AUDIOBOOK_DIRECTORY", "AUDIOBOOK_DIR", "M4A", "M4B"}
)


@dataclass(frozen=True, slots=True)
class LocalMetadataCandidate:
    """One metadata observation, identified by its local source."""

    source: LocalMetadataSource
    metadata: PublicationMetadata
    cover: bytes | None = None


@dataclass(frozen=True, slots=True)
class ResolvedLocalMetadata:
    """Metadata and cover selected from the configured local source order."""

    metadata: PublicationMetadata
    cover: bytes | None
    field_sources: tuple[tuple[str, LocalMetadataSource | Literal["REQUESTED"]], ...]
    source_order: tuple[LocalMetadataSource, ...]


@dataclass(frozen=True, slots=True)
class LocalAudioMetadata:
    """Metadata needed by local resolution for an inspected audio asset."""

    album: str | None = None
    author: str | None = None
    narrator: str | None = None
    series_name: str | None = None
    volume_index: float | None = None
    cover_data: bytes | None = None


class _LocalSidecarCandidateReader(Protocol):
    def __call__(
        self,
        metadata_source: Path,
        *,
        directory: bool,
    ) -> LocalMetadataCandidate | None: ...


class _LocalEmbeddedCandidateReader(Protocol):
    def __call__(
        self,
        source: Path,
        source_format: str,
    ) -> LocalMetadataCandidate | None: ...


class _LocalAudioMetadataReader(Protocol):
    def __call__(self, source: Path) -> LocalAudioMetadata: ...


class FilesystemLocalMetadataInspector:
    """Coordinate filesystem-backed local metadata source inspection.

    Format byte readers and safe sidecar discovery are injected ports.  The
    inspector itself owns the source selection and candidate composition, so an
    import worker and a synchronous cover operation cannot accidentally drift
    in their ``SIDECAR_OPF -> EMBEDDED -> PATH`` behaviour.
    """

    def __init__(
        self,
        *,
        embedded_reader: _LocalEmbeddedCandidateReader | None = None,
        audio_reader: _LocalAudioMetadataReader | None = None,
        sidecar_reader: _LocalSidecarCandidateReader | None = None,
    ) -> None:
        self._embedded_reader = embedded_reader
        self._audio_reader = audio_reader
        self._sidecar_reader = sidecar_reader

    def inspect(
        self,
        source: Path,
        *,
        resource_path: Path | None = None,
        source_format: str,
        audio: LocalAudioMetadata | None = None,
        embedded: LocalMetadataCandidate | None = None,
        sidecar: LocalMetadataCandidate | None = None,
        source_order: tuple[LocalMetadataSource, ...] = DEFAULT_LOCAL_METADATA_PRIORITY,
    ) -> ResolvedLocalMetadata:
        """Read and resolve local metadata for one source path.

        ``audio`` and ``embedded`` let an import adapter reuse observations it
        already made for asset metadata and navigation.  When omitted, the
        corresponding injected reader is called exactly once.  This avoids a
        second read in the import path while allowing synchronous callers to
        use the same inspector with only source paths.
        """

        normalized_format = source_format.strip().upper()
        is_audio = normalized_format in _AUDIO_FORMATS
        resolved_audio = audio
        if resolved_audio is None and is_audio and self._audio_reader is not None:
            resolved_audio = self._audio_reader(source)

        resolved_embedded = embedded
        if (
            resolved_embedded is None
            and not is_audio
            and self._embedded_reader is not None
        ):
            resolved_embedded = self._embedded_reader(source, normalized_format)

        return _parse_local_metadata(
            source,
            source_format=normalized_format,
            resource_path=resource_path,
            embedded=resolved_embedded,
            audio=resolved_audio,
            sidecar=sidecar,
            sidecar_reader=self._sidecar_reader,
            source_order=source_order,
        )


def _parse_local_metadata(
    source: Path,
    *,
    source_format: str,
    resource_path: Path | None = None,
    embedded: LocalMetadataCandidate | None = None,
    audio: LocalAudioMetadata | None = None,
    sidecar: LocalMetadataCandidate | None = None,
    sidecar_reader: _LocalSidecarCandidateReader | None = None,
    source_order: tuple[LocalMetadataSource, ...] = DEFAULT_LOCAL_METADATA_PRIORITY,
) -> ResolvedLocalMetadata:
    """Compose and resolve local metadata for one existing source.

    ``source`` is the inspected file.  For an audiobook directory,
    ``source_format`` must be ``"AUDIOBOOK_DIRECTORY"`` (or the persisted
    ``"AUDIOBOOK_DIR"`` label) and ``resource_path``
    is the directory whose name and sidecar belong to the resource.  For all
    file adapters, ``resource_path`` is ignored for source naming and the file
    itself supplies the path candidate.

    Format-specific embedded inspection remains an injected candidate because
    the imports capability owns those byte parsers.  ``audio`` is a neutral
    convenience DTO for the audio adapter, and is converted into the same
    ``EMBEDDED`` candidate used by every other format.  A caller may provide a
    sidecar candidate directly or a safe ``sidecar_reader`` port; providing
    both is rejected to avoid silently running two discovery policies.
    """

    if embedded is not None and audio is not None:
        raise ValueError("embedded and audio cannot both be supplied")
    if sidecar is not None and sidecar_reader is not None:
        raise ValueError("sidecar and sidecar_reader cannot both be supplied")

    normalized_format = source_format.strip().upper()
    is_directory_resource = normalized_format in _AUDIOBOOK_DIRECTORY_FORMATS
    has_directory_path = is_directory_resource and resource_path is not None
    metadata_source = (
        resource_path if is_directory_resource and resource_path is not None else source
    )

    resolved_sidecar = sidecar
    if resolved_sidecar is None and sidecar_reader is not None:
        resolved_sidecar = sidecar_reader(
            metadata_source,
            directory=is_directory_resource,
        )

    resolved_embedded = embedded
    if audio is not None:
        resolved_embedded = LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(
                title=audio.album if not is_directory_resource else None,
                authors=(audio.author,) if audio.author else (),
                narrators=(audio.narrator,) if audio.narrator else (),
                series_name=audio.series_name,
                volume_index=audio.volume_index,
            ),
            cover=audio.cover_data,
        )

    path_titles = titles_from_local_source(
        metadata_source.name if has_directory_path else metadata_source.stem
    )
    candidates: list[LocalMetadataCandidate] = [
        LocalMetadataCandidate(
            source="PATH",
            metadata=PublicationMetadata(
                title=path_titles.work_title,
                volume_title=path_titles.volume_title,
                volume_index=path_titles.volume_index,
            ),
        )
    ]
    if resolved_embedded is not None:
        candidates.append(resolved_embedded)
    if resolved_sidecar is not None:
        candidates.append(resolved_sidecar)
    return _resolve_local_metadata(tuple(candidates), source_order)


def _resolve_local_metadata(
    candidates: tuple[LocalMetadataCandidate, ...],
    source_order: tuple[LocalMetadataSource, ...] = DEFAULT_LOCAL_METADATA_PRIORITY,
) -> ResolvedLocalMetadata:
    """Resolve each publication field and cover independently by source order."""

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

    cover: bytes | None = None
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
    "FilesystemLocalMetadataInspector",
    "LocalAudioMetadata",
    "LocalMetadataCandidate",
    "ResolvedLocalMetadata",
]
