"""Recognize presentation metadata for a SourceNode-backed Book version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.library.application.recognized_metadata import (
    RecognizedMetadataUnitOfWork,
)
from app.modules.metadata.public import MatchDecision


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
    match: MatchDecision | None = None
    confirmable_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceNodeMetadataRecognitionResult:
    source_node_id: str
    provider_id: str
    query: str
    message: str | None
    candidates: tuple[SourceNodeMetadataCandidate, ...]
    target_revision: str | None = None
    book_revision: str | None = None
    assistance: dict[str, object] | None = None
    recognition_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    outcome: str | None = None


class SourceNodeMetadataRecognitionPort(Protocol):
    def reopen(self, book_id: str, record_id: str) -> SourceNodeMetadataRecognitionResult | None: ...

    def ignore(self, book_id: str, record_id: str) -> bool: ...

    def search(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
        resource_id: str | None = None,
    ) -> SourceNodeMetadataRecognitionResult | None: ...


class RecognizeSourceNodeMetadata:
    def __init__(self, port: SourceNodeMetadataRecognitionPort, unit_of_work: RecognizedMetadataUnitOfWork | None = None) -> None:
        self._port = port
        self._unit_of_work = unit_of_work

    def reopen(self, book_id: str, record_id: str) -> SourceNodeMetadataRecognitionResult | None:
        return self._port.reopen(book_id, record_id)

    def ignore(self, book_id: str, record_id: str) -> bool:
        if self._unit_of_work is None:
            raise RuntimeError("Recognition write transaction is not configured")
        try:
            result = self._port.ignore(book_id, record_id)
            self._unit_of_work.commit()
            return result
        except Exception:
            self._unit_of_work.rollback()
            raise

    def execute(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
        resource_id: str | None = None,
    ) -> SourceNodeMetadataRecognitionResult | None:
        normalized_provider = provider_id.strip()
        if not normalized_provider:
            raise ValueError("provider_id must not be empty")
        return self._port.search(
            book_id=book_id,
            source_node_id=source_node_id,
            provider_id=normalized_provider,
            query=(query or "").strip() or None,
            resource_id=resource_id,
        )


__all__ = [
    "MetadataProviderSearchError",
    "RecognizeSourceNodeMetadata",
    "SourceNodeMetadataCandidate",
    "SourceNodeMetadataRecognitionPort",
    "SourceNodeMetadataRecognitionResult",
]
