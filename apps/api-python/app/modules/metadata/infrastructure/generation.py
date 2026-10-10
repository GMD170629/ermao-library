"""Complete only missing description/tags after actual source detail acquisition."""

import json
import logging
from collections.abc import Callable, Mapping
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exception_diagnostics import capture_exception, record_exception
from app.core.i18n import configured_locale
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
)
from app.modules.metadata.infrastructure.ai_client import (
    generate_metadata,
    model_configured,
)
from app.modules.metadata.infrastructure.identity_context import identity_clues
from app.services.metadata_provider_registry import metadata_provider_runtime_config


def complete_missing_metadata(
    db: Session,
    *,
    book_id: str,
    candidate: Mapping[str, object] | None,
    source_node_id: str | None = None,
    scope: Literal["book", "resource"] | None = "book",
    resource_id: str | None = None,
    is_active: Callable[[], bool] | None = None,
) -> dict[str, object] | None:
    if candidate is None:
        return None
    result = dict(candidate)
    if scope is None:
        return result
    # A selected record belongs to this operation; never carry a previous generation.
    config = metadata_provider_runtime_config(db, "ai")
    identity = result.get("identity")
    if (
        config is None
        or config.get("generateEnabled") is not True
        or not model_configured(config)
        or not result.get("title")
        or not result.get("author")
        or isinstance(identity, dict)
        and identity.get("needsReview")
    ):
        return result
    book = db.get(LibraryBook, book_id)
    metadata = db.get(LibraryBookMetadata, book_id)
    if book is None or metadata is None:
        return result
    target: LibraryBookMetadata | LibraryReadableResourceMetadata | None = metadata
    resource = None
    if scope == "resource":
        resource = db.get(LibraryReadableResource, resource_id) if resource_id else None
        if resource is None or resource.book_id != book_id or resource.source_node_id != source_node_id:
            return result
        target = db.get(LibraryReadableResourceMetadata, resource.id)
        if target is None:
            return result
    if target is None:
        return result
    tags = list(
        db.scalars(
            select(LibraryFacet.name)
            .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .where(LibraryBookFacet.book_id == book_id, LibraryFacet.kind == "TAG")
        )
    )
    protected = set(json.loads(metadata.protected_fields or "[]"))
    description_protected = set(json.loads(target.protected_fields or "[]"))
    missing = []
    if (
        not (target.description or "").strip()
        and not str(result.get("description") or "").strip()
        and "description" not in description_protected
    ):
        missing.append("description")
    if not tags and not result.get("tags") and "tags" not in protected:
        missing.append("tags")
    if not missing:
        return result
    revision = metadata.updated_at.isoformat() + (
        "|" + target.updated_at.isoformat() if resource else ""
    )
    summary = {
        "title": result["title"],
        "author": result["author"],
        "missingFields": missing,
        "language": configured_locale(db),
        "websiteInformation": {
            key: result.get(key) for key in ("source", "id", "description", "tags")
        },
        **identity_clues(db, book_id, source_node_id),
    }
    db.close()
    if is_active is not None and not is_active():
        return result
    try:
        generated = generate_metadata(config, summary)
    except Exception as error:  # noqa: BLE001 - preserve usable A/B results on optional generation failure.
        capture_exception(error, persist=False)
        record_exception(
            logging.getLogger(__name__),
            "metadata.generate_failed",
            error,
        )
        return result
    fields = []
    if "description" in missing and (generated.description or "").strip():
        result["description"] = (generated.description or "").strip()
        fields.append("description")
    if "tags" in missing:
        tags = list(dict.fromkeys(tag.strip() for tag in generated.tags if tag.strip()))
        if tags:
            result["tags"] = tags
            fields.append("tags")
    if fields:
        result.update(
            generatedFields=fields,
            generationSource="AI_GENERATED",
            generationNeedsReview=generated.needsReview,
            generationReason=generated.reason,
            generationRevision=revision,
        )
    return result
