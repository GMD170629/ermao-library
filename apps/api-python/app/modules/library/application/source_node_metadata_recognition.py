"""Recognize presentation metadata for a SourceNode-backed Book version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class MetadataProviderSearchError(Exception):
    """A configured metadata provider could not complete a search."""


@dataclass(frozen=True, slots=True)
class SourceNodeMetadataCandidate:
    id: str
    source: str
    title: str | None
    author: str | None
    description: str | None
    tags: tuple[str, ...]
    series_name: str | None
    series_index: float | None
    publisher: str | None
    published_at: str | None
    language: str | None
    isbn: str | None
    identifier: str | None
    narrator: str | None
    abridged: bool | None
    resource_index: float | None
    cover_url: str | None
    confidence: float


@dataclass(frozen=True, slots=True)
class SourceNodeMetadataRecognitionResult:
    source_node_id: str
    provider_id: str
    query: str
    message: str | None
    candidates: tuple[SourceNodeMetadataCandidate, ...]


class SourceNodeMetadataRecognitionPort(Protocol):
    def search(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
    ) -> SourceNodeMetadataRecognitionResult | None: ...


class RecognizeSourceNodeMetadata:
    def __init__(self, port: SourceNodeMetadataRecognitionPort) -> None:
        self._port = port

    def execute(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
    ) -> SourceNodeMetadataRecognitionResult | None:
        normalized_provider = provider_id.strip()
        if not normalized_provider:
            raise ValueError("provider_id must not be empty")
        return self._port.search(
            book_id=book_id,
            source_node_id=source_node_id,
            provider_id=normalized_provider,
            query=(query or "").strip() or None,
        )


__all__ = [
    "MetadataProviderSearchError",
    "RecognizeSourceNodeMetadata",
    "SourceNodeMetadataCandidate",
    "SourceNodeMetadataRecognitionPort",
    "SourceNodeMetadataRecognitionResult",
]
