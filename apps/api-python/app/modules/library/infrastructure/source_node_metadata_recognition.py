"""Metadata-provider adapter for SourceNode version recognition."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace

from sqlalchemy.orm import Session

from app.modules.library.application.source_node_metadata_recognition import (
    MetadataProviderSearchError,
    SourceNodeMetadataCandidate,
    SourceNodeMetadataRecognitionPort,
    SourceNodeMetadataRecognitionResult,
)
from app.modules.metadata.public import (
    assess_candidates,
    load_recognition_context,
    provider_context,
    search_with_metadata_provider,
)


class ProviderSourceNodeMetadataRecognition(SourceNodeMetadataRecognitionPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        book_id: str,
        source_node_id: str,
        provider_id: str,
        query: str | None,
        resource_id: str | None = None,
    ) -> SourceNodeMetadataRecognitionResult | None:
        recognition = load_recognition_context(
            self._db,
            book_id=book_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
        )
        if recognition is None:
            return None
        context = provider_context(self._db, recognition)
        title = recognition.identity.title
        try:
            result = search_with_metadata_provider(
                self._db,
                context,
                provider_id,
                query or title,
            )
        except Exception as exc:
            raise MetadataProviderSearchError(provider_id) from exc
        raw_candidates = result.get("candidates")
        assessed = assess_candidates(
            recognition,
            provider_id,
            [
                {str(key): item for key, item in value.items()}
                for value in raw_candidates
                if isinstance(value, Mapping)
            ]
            if isinstance(raw_candidates, list)
            else [],
        )
        candidates = tuple(
            replace(candidate, match=decision)
            for value, decision in assessed
            if (candidate := self._candidate(value, provider_id)) is not None
        )
        return SourceNodeMetadataRecognitionResult(
            source_node_id=source_node_id,
            provider_id=provider_id,
            query=query or title,
            message=str(result["message"]) if result.get("message") else None,
            candidates=candidates,
        )

    @staticmethod
    def _candidate(
        value: Mapping[str, object], provider_id: str
    ) -> SourceNodeMetadataCandidate | None:
        identifier = str(value.get("id") or "").strip()
        if not identifier:
            return None
        confidence_value = value.get("confidence")
        confidence = (
            float(confidence_value)
            if isinstance(confidence_value, (int, float))
            and not isinstance(confidence_value, bool)
            and math.isfinite(float(confidence_value))
            else 0.0
        )
        confidence = min(1.0, max(0.0, confidence))
        tags_value = value.get("tags")
        tags = (
            tuple(
                str(tag).strip()
                for tag in tags_value
                if isinstance(tag, str) and str(tag).strip()
            )
            if isinstance(tags_value, (list, tuple))
            else ()
        )

        def optional_string(key: str) -> str | None:
            candidate_value = value.get(key)
            return (
                str(candidate_value).strip()
                if candidate_value is not None and str(candidate_value).strip()
                else None
            )

        def optional_number(key: str) -> float | None:
            candidate_value = value.get(key)
            if isinstance(candidate_value, bool) or not isinstance(
                candidate_value, (int, float)
            ):
                return None
            parsed = float(candidate_value)
            return parsed if math.isfinite(parsed) else None

        abridged_value = value.get("abridged")
        return SourceNodeMetadataCandidate(
            id=identifier,
            source=provider_id,
            title=optional_string("title"),
            author=optional_string("author"),
            description=optional_string("description"),
            tags=tags,
            series_name=optional_string("seriesName"),
            series_index=optional_number("seriesIndex"),
            publisher=optional_string("publisher"),
            published_at=optional_string("publishedAt"),
            language=optional_string("language"),
            isbn=optional_string("isbn"),
            identifier=optional_string("identifier"),
            narrator=optional_string("narrator"),
            abridged=abridged_value if isinstance(abridged_value, bool) else None,
            resource_index=optional_number("resourceIndex"),
            cover_url=optional_string("coverUrl"),
            confidence=confidence,
        )


__all__ = ["ProviderSourceNodeMetadataRecognition"]
