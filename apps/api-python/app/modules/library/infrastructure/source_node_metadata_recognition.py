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
from app.modules.library.infrastructure.metadata_patches import (
    SqlAlchemyMetadataPatches,
)
from app.modules.metadata.public import (
    assess_candidates,
    candidate_evidence,
    confirm_candidate,
    ignore_recognition_record,
    load_recognition_context,
    propose_fields,
    provider_context,
    recognition_fingerprint,
    recognition_record,
    save_recognition_record,
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
        snapshots = SqlAlchemyMetadataPatches(self._db)
        target_snapshot = snapshots.snapshot(recognition.target_type, recognition.target_id, frozenset({recognition.library_id}))
        book_snapshot = snapshots.snapshot("book", book_id, frozenset({recognition.library_id}))
        context = provider_context(self._db, recognition)
        context["explicitManualQuery"] = True
        title = recognition.identity.title
        try:
            result = search_with_metadata_provider(
                self._db,
                context,
                provider_id,
                query,
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
            replace(candidate, match=decision, confirmable_fields=tuple(proposal.field for proposal in
                propose_fields(recognition, provider_id, value, confirm_candidate(recognition, candidate_evidence(provider_id, value)))))
            for value, decision in assessed
            if (candidate := self._candidate(value, provider_id)) is not None
        )
        record_id = save_recognition_record(self._db, recognition, source_node_id, provider_id, assessed, query or title) if provider_id != "ai" else None
        return SourceNodeMetadataRecognitionResult(
            recognition_id=record_id, target_type=recognition.target_type, target_id=recognition.target_id,
            assistance=result.get("assistance"),
            target_revision=target_snapshot.revision if target_snapshot else None,
            book_revision=book_snapshot.revision if book_snapshot else None,
            source_node_id=source_node_id,
            provider_id=provider_id,
            query=query or title,
            message=str(result["message"]) if result.get("message") else None,
            candidates=candidates,
        )

    def ignore(self, book_id: str, record_id: str) -> bool:
        return ignore_recognition_record(self._db, book_id, record_id)

    def reopen(self, book_id: str, record_id: str) -> SourceNodeMetadataRecognitionResult | None:
        raw = recognition_record(self._db, book_id, record_id)
        if raw is None:
            return None
        saved = raw["recognition"]
        context = load_recognition_context(self._db, book_id=book_id, source_node_id=saved.get("sourceNodeId"),
            resource_id=saved.get("targetId") if saved.get("targetType") == "resource" else None)
        if context is None or recognition_fingerprint(context) != saved.get("fingerprint") or saved.get("ignored") or saved.get("humanConfirmed"):
            raise ValueError("METADATA_CHANGED")
        candidates = []
        for attempt in raw.get("attempted", [])[:8]:
            provider = str(attempt.get("provider") or "")
            values = attempt.get("candidates", attempt.get("exactCandidates", []))[:10]
            for value, decision in assess_candidates(context, provider, values):
                candidate = self._candidate(value, provider)
                if candidate:
                    confirmed = confirm_candidate(context, candidate_evidence(provider, value))
                    candidates.append(replace(candidate, match=decision, confirmable_fields=tuple(item.field for item in propose_fields(context, provider, value, confirmed))))
        port = SqlAlchemyMetadataPatches(self._db)
        target = port.snapshot(context.target_type, context.target_id, frozenset({context.library_id}))
        parent = port.snapshot("book", book_id, frozenset({context.library_id}))
        return SourceNodeMetadataRecognitionResult(source_node_id=str(saved.get("sourceNodeId") or ""), provider_id=candidates[0].source if candidates else "",
            query=str(saved.get("query") or context.identity.title), message=None, candidates=tuple(candidates[:10]),
            target_revision=target.revision if target else None, book_revision=parent.revision if parent else None,
            recognition_id=record_id, target_type=context.target_type, target_id=context.target_id, outcome=saved.get("outcome"), assistance=saved.get("aiAssistance"))

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
