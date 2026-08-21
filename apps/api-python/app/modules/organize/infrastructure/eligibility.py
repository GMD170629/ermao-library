"""ORM eligibility queries for organize scheduling."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.time import timestamp_ms_to_datetime, to_timestamp_ms
from app.models import (
    LibraryReadableResource,
    LibraryBook,
    LibraryBookMetadata,
)
from app.models.organize import OrganizeJob
from app.modules.library.infrastructure.media_kind_sql import (
    resource_media_kind,
)

UNRESOLVED_JOB_STATUSES = (
    "LOOKUP_PENDING",
    "PENDING",
    "QUEUED",
    "RUNNING",
    "RETRY_WAIT",
    "REVIEWING",
    "FAILED",
)


def book_entity_record(
    entity: LibraryBook,
    metadata: LibraryBookMetadata | None,
) -> dict[str, Any]:
    return {
        "id": entity.id,
        "libraryId": entity.library_id,
        "title": metadata.title if metadata else "",
        "normalizedTitle": metadata.normalized_title if metadata else "",
        "author": metadata.author if metadata else None,
        "normalizedAuthor": metadata.normalized_author if metadata else None,
        "description": metadata.description if metadata else None,
        "publicationStatus": metadata.publication_status if metadata else "UNKNOWN",
        "trackingStatus": metadata.tracking_status if metadata else "NOT_TRACKING",
        "tags": "[]",
        "seriesName": metadata.series_name if metadata else None,
        "seriesIndex": metadata.series_index if metadata else None,
        "metadataQuality": metadata.metadata_quality if metadata else 0,
        "organizeStatus": None,
        "coverPath": metadata.cover_path if metadata else None,
        "coverStatus": metadata.cover_status if metadata else "PENDING",
        "hidden": entity.visibility_state != "VISIBLE",
        "organized": entity.curation_state not in {"PENDING", "UNASSESSED"},
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def reason_codes_for_book(
    book: dict[str, Any],
    rules: dict[str, Any],
    *,
    force_selected: bool = False,
) -> list[str]:
    if force_selected:
        return ["MANUAL_SELECTED"]
    reasons: list[str] = []
    if rules.get("unrecognized") and not bool(book.get("organized")):
        reasons.append("UNRECOGNIZED")
    missing = any(
        not str(book.get(field) or "").strip() for field in ("author", "coverPath")
    )
    if rules.get("missingMetadata") and missing:
        reasons.append("MISSING_METADATA")
    return reasons


def select_eligible_works(
    db: Session,
    *,
    rules: dict[str, Any],
    book_ids: list[str] | None = None,
    trigger: str = "MANUAL",
    limit: int = 500,
    force_selected: bool = False,
    auto_run_on_new_since: Any = None,
) -> list[dict[str, Any]]:
    bounded = min(max(int(limit), 1), 2000)
    filters = [
        LibraryBook.visibility_state == "VISIBLE",
        LibraryBook.curation_state != "DISMISSED",
    ]
    if book_ids:
        normalized_ids = list(
            dict.fromkeys(str(item) for item in book_ids if str(item).strip())
        )
        if not normalized_ids:
            return []
        filters.append(LibraryBook.id.in_(normalized_ids))

    unresolved_exists = (
        select(OrganizeJob.id)
        .where(
            OrganizeJob.book_id == LibraryBook.id,
            OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
        )
        .exists()
    )
    filters.append(~unresolved_exists)
    if trigger == "NEW":
        new_trigger_exists = (
            select(OrganizeJob.id)
            .where(
                OrganizeJob.book_id == LibraryBook.id, OrganizeJob.trigger == "NEW"
            )
            .exists()
        )
        filters.append(~new_trigger_exists)

    if trigger == "NEW":
        if not auto_run_on_new_since:
            return []
        since_ms = to_timestamp_ms(auto_run_on_new_since)
        since_dt = timestamp_ms_to_datetime(since_ms)
        if since_dt is None:
            return []
        filters.append(LibraryBook.created_at >= since_dt)

    books = db.execute(
        select(LibraryBook, LibraryBookMetadata)
        .outerjoin(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(*filters)
        .order_by(LibraryBook.created_at.asc(), LibraryBook.id.asc())
        .limit(bounded)
    ).all()

    result: list[dict[str, Any]] = []
    for entity, metadata in books:
        book = book_entity_record(entity, metadata)
        media_kind = resource_media_kind(LibraryReadableResource)
        book["availableMediaKinds"] = list(
            db.scalars(
                select(media_kind.label("media_kind"))
                .select_from(LibraryReadableResource)
                .where(
                    LibraryReadableResource.book_id == entity.id,
                    LibraryReadableResource.enablement_state == "ENABLED",
                )
                .group_by(media_kind)
                .order_by(
                    case(
                        (media_kind == "EBOOK", 0),
                        (media_kind == "COMIC", 1),
                        (media_kind == "AUDIOBOOK", 2),
                        else_=3,
                    )
                )
            ).all()
        )
        reasons = reason_codes_for_book(book, rules, force_selected=force_selected)
        if reasons:
            result.append({**book, "reasonCodes": reasons})
    return result


def first_resource_selection_for_book(
    db: Session, book_id: str, preferred_resource_id: str | None = None
) -> tuple[str, str, str | None] | None:
    media_kind = resource_media_kind(LibraryReadableResource)
    filters = [
        LibraryReadableResource.book_id == book_id,
        LibraryReadableResource.enablement_state == "ENABLED",
    ]
    if preferred_resource_id:
        filters.append(LibraryReadableResource.id == preferred_resource_id)
    row = db.execute(
        select(LibraryReadableResource)
        .where(*filters)
        .order_by(
            case(
                (media_kind == "EBOOK", 0),
                (media_kind == "COMIC", 1),
                (media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            LibraryReadableResource.created_at.asc(),
            LibraryReadableResource.id.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    resource = row[0]
    return (str(resource.id), str(resource.media_kind), str(resource.id))
