"""Metadata-provider adapter for SourceNode version recognition."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exception_diagnostics import record_exception
from app.core.i18n import configured_locale
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.models.organize import OrganizePolicy
from app.modules.library.application.source_node_metadata_recognition import (
    MetadataProviderSearchError,
    SourceNodeMetadataCandidate,
    SourceNodeMetadataRecognitionPort,
    SourceNodeMetadataRecognitionResult,
)
from app.modules.metadata.public import (
    MetadataMatch,
    candidate_key,
    complete_missing_metadata,
    enabled_metadata_provider_ids,
    match_metadata_candidates,
    prepare_matched_metadata,
    recognize_metadata_identity,
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
        scope: Literal["book", "resource"] | None = None,
        resource_id: str | None = None,
        manual_query: bool = False,
        selected_candidate: Mapping[str, object] | None = None,
        is_active: Callable[[], bool] | None = None,
    ) -> SourceNodeMetadataRecognitionResult | None:
        book_row = self._db.execute(
            select(LibraryBook, LibraryBookMetadata)
            .join(
                LibraryBookMetadata,
                LibraryBookMetadata.book_id == LibraryBook.id,
            )
            .where(LibraryBook.id == book_id)
        ).one_or_none()
        node_row = self._db.execute(
            select(LibrarySourceNode, LibrarySourceNodeMetadata)
            .outerjoin(
                LibrarySourceNodeMetadata,
                LibrarySourceNodeMetadata.source_node_id == LibrarySourceNode.id,
            )
            .where(LibrarySourceNode.id == source_node_id)
        ).one_or_none()
        if book_row is None or node_row is None:
            return None
        book, book_metadata = book_row
        node, node_metadata = node_row
        root = self._db.get(LibrarySourceNode, book.source_node_id)
        if (
            root is None
            or node.library_id != root.library_id
            or not (
                node.id == root.id
                or node.relative_path.startswith(f"{root.relative_path.rstrip('/')}/")
            )
        ):
            return None
        # Compatibility for old callers only. New resource callers name their target.
        if scope is None:
            if resource_id is not None:
                return None
            if source_node_id == book.source_node_id:
                scope = "book"
            else:
                legacy_resources = list(self._db.scalars(select(LibraryReadableResource).where(
                    LibraryReadableResource.book_id == book_id,
                    LibraryReadableResource.source_node_id == source_node_id,
                ).limit(2)))
                if len(legacy_resources) == 1:
                    scope, resource_id = "resource", legacy_resources[0].id
        if scope == "resource":
            target_resource = self._db.get(LibraryReadableResource, resource_id) if resource_id else None
            if target_resource is None or target_resource.book_id != book_id or target_resource.source_node_id != source_node_id:
                return None
        elif resource_id is not None:
            return None
        resources = [
            {
                "format": resource.format,
                "hidden": resource.enablement_state != "ENABLED",
            }
            for resource in self._db.scalars(
                select(LibraryReadableResource)
                .join(
                    LibrarySourceNode,
                    LibrarySourceNode.id == LibraryReadableResource.source_node_id,
                )
                .where(
                    LibraryReadableResource.book_id == book_id,
                    (LibrarySourceNode.id == node.id)
                    | LibrarySourceNode.relative_path.startswith(
                        f"{node.relative_path.rstrip('/')}/",
                        autoescape=True,
                    ),
                )
                .order_by(
                    LibraryReadableResource.created_at, LibraryReadableResource.id
                )
            )
        ]
        resource_title = self._db.scalar(
            select(LibraryReadableResourceMetadata.title)
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id
                == LibraryReadableResourceMetadata.resource_id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.source_node_id == node.id,
            )
            .limit(1)
        )
        title = (
            book_metadata.title
            if node.id == root.id
            else resource_title
            or (
                node_metadata.title.strip()
                if node_metadata is not None and node_metadata.title
                else node.name
            )
        )
        book_context: dict[str, object] = {
            "id": book.id,
            "title": title,
            "author": book_metadata.author,
            "description": node_metadata.description if node_metadata else None,
            "seriesName": book_metadata.series_name,
            "seriesIndex": book_metadata.series_index,
        }
        context: dict[str, object] = {"book": book_context, "resources": resources}
        policy = self._db.scalars(select(OrganizePolicy).limit(1)).first()
        prefer_local = policy.prefer_local_metadata if policy is not None else True
        target_id = node.id
        disabled_message = "AI-assisted recognition is disabled" if configured_locale(self._db) == "en-US" else "AI 增强识别未启用"
        if selected_candidate is not None:
            value = dict(selected_candidate)
            for field in cast(list[str], value.pop("generatedFields", [])):
                if field in ("description", "tags"):
                    value[field] = None
            for key in ("generationSource", "generationNeedsReview", "generationReason", "generationRevision", "sourceIssues"):
                value.pop(key, None)
            source = str(value["source"])
            identifier = str(value["id"])
            prefix = f"{source}:"
            if identifier.startswith(prefix):
                value["id"] = identifier[len(prefix):]
            match = MetadataMatch(None, candidate_key(value))
            selected = prepare_matched_metadata(self._db, match, [value])
            selected = complete_missing_metadata(self._db, book_id=book_id, source_node_id=source_node_id, candidate=selected, scope=scope, resource_id=resource_id, is_active=is_active)
            if selected:
                selected["id"] = identifier
            return SourceNodeMetadataRecognitionResult(
                source_node_id=source_node_id, provider_id=provider_id,
                query=query or title, message=None, candidates=(),
                selected_id=identifier, prefer_local_metadata=prefer_local,
                selected_metadata=self._candidate(selected, source) if selected else None,
            )
        if manual_query:
            book_context = {**book_context, "title": query or title, "author": None}
            context["book"] = book_context
        try:
            identity = None
            if not manual_query or provider_id == "ai":
                identity = recognize_metadata_identity(
                    self._db,
                    book_id=book_id,
                    source_node_id=target_id,
                    title=str(book_context["title"]),
                    author=None if manual_query else book_metadata.author,
                )
            if identity is not None and not manual_query:
                book_context = {
                    **book_context,
                    "title": identity.title or title,
                    "author": identity.author,
                }
                context["book"] = book_context
            effective_query = (
                identity.title
                if not manual_query and identity and identity.title
                else query or title
            )
            values: list[dict[str, object]] = []
            source_issues: list[str] = []
            source_completed = False
            # Query only enabled existing sources, once each, in preferred order.
            providers = list(dict.fromkeys([provider_id, *enabled_metadata_provider_ids(self._db)]))
            for source in (item for item in providers if item != "ai"):
                try:
                    result = search_with_metadata_provider(self._db, context, source, effective_query)
                except Exception as error:  # noqa: BLE001 - one source must not block others.
                    record_exception(logging.getLogger(__name__), "metadata.source_search_failed", error,
                                     context={"step": "source_search", "resource_id": source})
                    source_issues.append(f"{source}:search_failed")
                    continue
                source_completed = source_completed or result.get("enabled") is not False
                raw = result.get("candidates", [])
                if isinstance(raw, list):
                    values.extend({**item, "source": source} for item in raw[:10]
                                  if isinstance(item, dict) and item.get("id"))
            match = match_metadata_candidates(
                self._db, book_id=book_id, source_node_id=target_id,
                title=effective_query, author=str(book_context.get("author") or "") or None,
                identity=identity, candidates=values, manual_query=manual_query,
                local_title=title, local_author=book_metadata.author,
            )
            identity = match.identity
            selected = prepare_matched_metadata(self._db, match, values)
            selected = complete_missing_metadata(self._db, book_id=book_id, source_node_id=source_node_id, candidate=selected, scope=scope, resource_id=resource_id, is_active=is_active)
            if selected:
                selected["sourceIssues"] = [*source_issues, *cast(list[str], selected.get("sourceIssues", [])), *(["no_matching_entry"] if source_completed and not match.primary_candidate_id else [])]
            # Display raw records separately from the normalized/merged application.
            values = [{**value, "id": candidate_key(value)} for value in values]
            if selected and selected.get("source") != "ai":
                selected = {**selected, "id": match.primary_candidate_id}
            if identity is not None and (identity.title or identity.author):
                values.append(identity.candidate())
        except Exception as exc:
            raise MetadataProviderSearchError(provider_id) from exc
        candidates = tuple(
            candidate
            for value in values
            if isinstance(value, Mapping)
            and (candidate := self._candidate(value, provider_id)) is not None
        )
        return SourceNodeMetadataRecognitionResult(
            source_node_id=source_node_id,
            provider_id=provider_id,
            query=effective_query,
            identity=identity,
            selected_id=str(selected["id"]) if selected else None,
            prefer_local_metadata=prefer_local,
            message=identity.reason if identity else disabled_message if provider_id == "ai" else None,
            selected_metadata=self._candidate(selected, provider_id) if selected else None,
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
            source=str(value.get("source") or provider_id),
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
            generated_fields=tuple(str(field) for field in cast(list[str], value.get("generatedFields", [])) if field in ("description", "tags")),
            generation_source="AI_GENERATED" if value.get("generatedFields") else None,
            generation_needs_review=value.get("generationNeedsReview") is True,
            generation_reason=optional_string("generationReason"),
            generation_revision=optional_string("generationRevision"),
            source_issues=tuple(str(issue) for issue in cast(list[str], value.get("sourceIssues", []))),
        )


__all__ = ["ProviderSourceNodeMetadataRecognition"]
