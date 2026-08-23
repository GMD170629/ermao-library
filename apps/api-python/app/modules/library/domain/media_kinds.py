"""Resource media-kind derivation from format and classification metadata."""

from __future__ import annotations

from typing import Protocol

_AUDIO_FORMATS = frozenset({"AUDIO", "AUDIOBOOK", "MP3", "M4A", "M4B"})
_COMIC_FORMATS = frozenset({"COMIC", "CBR", "CBZ", "RAR", "ZIP"})
_ASSIGNED_KINDS = frozenset({"EBOOK", "COMIC", "AUDIOBOOK"})


class ResourceMediaKindSource(Protocol):
    format: str
    classification_source: str
    suggested_media_kind: str | None


def media_kind_for_format(resource_format: str) -> str:
    normalized = resource_format.strip().upper()
    if normalized in _AUDIO_FORMATS:
        return "AUDIOBOOK"
    if normalized in _COMIC_FORMATS:
        return "COMIC"
    return "EBOOK"


def effective_media_kind(
    *,
    format: str,
    classification_source: str,
    suggested_media_kind: str | None,
) -> str:
    assigned = (suggested_media_kind or "").strip().upper()
    if classification_source == "USER" and assigned in _ASSIGNED_KINDS:
        return assigned
    return media_kind_for_format(format)


def media_kind_of(resource: ResourceMediaKindSource) -> str:
    return effective_media_kind(
        format=resource.format,
        classification_source=resource.classification_source,
        suggested_media_kind=resource.suggested_media_kind,
    )
