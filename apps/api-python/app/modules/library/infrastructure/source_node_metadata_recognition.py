"""Metadata-provider adapter for SourceNode version recognition."""

from __future__ import annotations

import math
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.modules.library.application.source_node_metadata_recognition import (
    MetadataProviderSearchError,
    SourceNodeMetadataCandidate,
    SourceNodeMetadataRecognitionPort,
    SourceNodeMetadataRecognitionResult,
)
from app.modules.metadata.public import search_with_metadata_provider


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
        title = (
            node_metadata.title.strip()
            if node_metadata is not None and node_metadata.title
            else node.name
        )
        context = {
            "book": {
                "id": book.id,
                "title": title,
                "author": book_metadata.author,
                "description": node_metadata.description if node_metadata else None,
                "seriesName": book_metadata.series_name,
                "seriesIndex": book_metadata.series_index,
            },
            "resources": resources,
        }
        try:
            result = search_with_metadata_provider(
                self._db,
                context,
                provider_id,
                query or title,
            )
        except Exception as exc:
            raise MetadataProviderSearchError(provider_id) from exc
        candidates = tuple(
            candidate
            for value in result.get("candidates", [])
            if isinstance(value, Mapping)
            and (candidate := self._candidate(value, provider_id)) is not None
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
        value: Mapping[object, object], provider_id: str
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
        )


__all__ = ["ProviderSourceNodeMetadataRecognition"]
