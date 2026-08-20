"""ORM eligibility queries for organize scheduling."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, inspect, select
from sqlalchemy.orm import Session

from app.core.time import timestamp_ms_to_datetime, to_timestamp_ms
from app.models.library import (
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import OrganizeJob
from app.modules.library.domain.media_kinds import media_kind_of
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.modules.library.infrastructure.media_kind_sql import (
    volume_effective_media_kind,
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


def work_entity_as_legacy_dict(entity: LibraryWork) -> dict[str, Any]:
    return {
        "id": entity.id,
        "libraryId": entity.library_id,
        "origin": entity.origin,
        "title": entity.title,
        "normalizedTitle": entity.normalized_title,
        "author": entity.author,
        "normalizedAuthor": entity.normalized_author,
        "description": entity.description,
        "publicationStatus": entity.publication_status,
        "trackingStatus": entity.tracking_status,
        "localLatestVolume": entity.local_latest_volume,
        "localLatestChapter": entity.local_latest_chapter,
        "localLatestTitle": entity.local_latest_title,
        "localLatestAt": entity.local_latest_at,
        "tags": entity.tags,
        "seriesName": entity.series_name,
        "seriesIndex": entity.series_index,
        "metadataQuality": entity.metadata_quality,
        "organizeStatus": entity.organize_status,
        "coverPath": entity.cover_path,
        "coverStatus": entity.cover_status,
        "hidden": entity.hidden,
        "organized": entity.organized,
        "mergeKey": entity.merge_key,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def reason_codes_for_work(
    work: dict[str, Any],
    rules: dict[str, Any],
    *,
    force_selected: bool = False,
) -> list[str]:
    if force_selected:
        return ["MANUAL_SELECTED"]
    reasons: list[str] = []
    if rules.get("unrecognized") and not bool(work.get("organized")):
        reasons.append("UNRECOGNIZED")
    missing = any(
        not str(work.get(field) or "").strip() for field in ("author", "coverPath")
    )
    if rules.get("missingMetadata") and missing:
        reasons.append("MISSING_METADATA")
    return reasons


def select_eligible_works(
    db: Session,
    *,
    rules: dict[str, Any],
    work_ids: list[str] | None = None,
    trigger: str = "MANUAL",
    limit: int = 500,
    force_selected: bool = False,
    auto_run_on_new_since: Any = None,
) -> list[dict[str, Any]]:
    if not inspect(db.connection()).has_table("LibraryWork"):
        return []

    bounded = min(max(int(limit), 1), 2000)
    filters = [
        func.coalesce(LibraryWork.hidden, False).is_(False),
        func.coalesce(LibraryWork.organize_status, "") != "DISMISSED",
    ]
    if work_ids:
        normalized_ids = list(
            dict.fromkeys(str(item) for item in work_ids if str(item).strip())
        )
        if not normalized_ids:
            return []
        filters.append(LibraryWork.id.in_(normalized_ids))

    if inspect(db.connection()).has_table("OrganizeJob"):
        unresolved_exists = (
            select(OrganizeJob.id)
            .where(
                OrganizeJob.work_id == LibraryWork.id,
                OrganizeJob.status.in_(UNRESOLVED_JOB_STATUSES),
            )
            .exists()
        )
        filters.append(~unresolved_exists)
        if trigger == "NEW":
            new_trigger_exists = (
                select(OrganizeJob.id)
                .where(
                    OrganizeJob.work_id == LibraryWork.id, OrganizeJob.trigger == "NEW"
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
        filters.append(LibraryWork.created_at >= since_dt)

    works = db.scalars(
        select(LibraryWork)
        .where(*filters)
        .order_by(LibraryWork.created_at.asc(), LibraryWork.id.asc())
        .limit(bounded)
    ).all()

    result: list[dict[str, Any]] = []
    for entity in works:
        work = work_entity_as_legacy_dict(entity)
        media_kind = volume_effective_media_kind(LibraryVolume)
        work["availableMediaKinds"] = list(
            db.scalars(
                select(media_kind.label("media_kind"))
                .select_from(LibraryVolume)
                .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
                .where(
                    LibraryVersion.work_id == entity.id,
                    LibraryVolume.hidden.is_(False),
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
        reasons = reason_codes_for_work(work, rules, force_selected=force_selected)
        if reasons:
            result.append({**work, "reasonCodes": reasons})
    return result


def first_version_selection_for_work(
    db: Session, work_id: str, preferred_version_id: str | None = None
) -> tuple[str, str, str | None] | None:
    inspector = inspect(db.connection())
    if not all(
        inspector.has_table(table) for table in ("LibraryVersion", "LibraryVolume")
    ):
        return None
    media_kind = volume_effective_media_kind(LibraryVolume)
    filters = [
        LibraryVersion.work_id == work_id,
        LibraryVolume.hidden.is_(False),
    ]
    if preferred_version_id:
        filters.append(LibraryVersion.id == preferred_version_id)
    row = db.execute(
        select(LibraryVolume, LibraryVersion)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(*filters)
        .order_by(
            case(
                (media_kind == "EBOOK", 0),
                (media_kind == "COMIC", 1),
                (media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            case(
                (LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY, 0),
                else_=1,
            ),
            func.coalesce(LibraryVersion.source_name, ""),
            LibraryVersion.source_key.asc(),
            LibraryVersion.id.asc(),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    volume, version = row
    return (str(version.id), media_kind_of(volume), str(volume.id))
