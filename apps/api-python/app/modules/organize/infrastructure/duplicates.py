"""ORM persistence for duplicate candidates and work merge actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, delete, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.organize import DuplicateCandidate, MetadataLookupTask
from app.modules.organize.infrastructure.eligibility import work_entity_as_legacy_dict


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


def duplicate_entity_as_legacy_dict(entity: DuplicateCandidate) -> dict[str, Any]:
    return {
        "id": entity.id,
        "jobId": entity.job_id,
        "targetWorkId": entity.target_work_id,
        "reasons": entity.reasons,
        "confidence": entity.confidence,
        "suggestedAction": entity.suggested_action,
        "status": entity.status,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def volume_entity_as_dict(entity: LibraryVolume) -> dict[str, Any]:
    return {
        "id": entity.id,
        "mediaVersionId": entity.media_version_id,
        "title": entity.title,
        "volumeIndex": entity.volume_index,
        "sortOrder": entity.sort_order,
        "format": entity.format,
        "resourceKey": entity.resource_key,
        "importStatus": entity.import_status,
        "importError": entity.import_error,
        "isbn": entity.isbn,
        "identifier": entity.identifier,
        "hidden": entity.hidden,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def list_duplicates_by_ids(
    db: Session, *, job_id: str, duplicate_ids: list[str]
) -> list[dict[str, Any]]:
    if not duplicate_ids or not _has_table(db, "DuplicateCandidate"):
        return []
    rows = db.scalars(
        select(DuplicateCandidate).where(
            DuplicateCandidate.job_id == job_id,
            DuplicateCandidate.id.in_(duplicate_ids),
        )
    ).all()
    return [duplicate_entity_as_legacy_dict(row) for row in rows]


def delete_pending_duplicates(db: Session, job_id: str) -> None:
    if not _has_table(db, "DuplicateCandidate"):
        return
    db.execute(
        delete(DuplicateCandidate).where(
            DuplicateCandidate.job_id == job_id,
            func.coalesce(DuplicateCandidate.status, "PENDING") == "PENDING",
        )
    )


def dismiss_pending_duplicates(db: Session, job_id: str) -> None:
    if not _has_table(db, "DuplicateCandidate"):
        return
    db.execute(
        update(DuplicateCandidate)
        .where(
            DuplicateCandidate.job_id == job_id,
            DuplicateCandidate.status == "PENDING",
        )
        .values(status="DISMISSED")
    )


def insert_duplicate_candidate(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    target_work_id: str,
    reasons_json: str,
    confidence: float,
    suggested_action: str,
    now: Any,
) -> None:
    db.add(
        DuplicateCandidate(
            id=candidate_id,
            job_id=job_id,
            target_work_id=target_work_id,
            reasons=reasons_json,
            confidence=confidence,
            suggested_action=suggested_action,
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()


def mark_duplicate_applied(db: Session, *, duplicate_id: str, now: Any) -> None:
    db.execute(
        update(DuplicateCandidate)
        .where(DuplicateCandidate.id == duplicate_id)
        .values(status="APPLIED", updated_at=now)
    )


def list_visible_works_except(db: Session, work_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryWork"):
        return []
    rows = db.scalars(
        select(LibraryWork).where(
            LibraryWork.id != work_id, LibraryWork.hidden.is_(False)
        )
    ).all()
    return [work_entity_as_legacy_dict(row) for row in rows]


def first_visible_volume(db: Session, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryVolume"):
        return None
    entity = db.scalars(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryMediaVersion.work_id == work_id,
            LibraryVolume.hidden.is_(False),
        )
        .order_by(
            case(
                (LibraryMediaVersion.media_kind == "EBOOK", 0),
                (LibraryMediaVersion.media_kind == "COMIC", 1),
                (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                else_=3,
            ),
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
        .limit(1)
    ).first()
    return volume_entity_as_dict(entity) if entity is not None else None


def set_work_hidden(
    db: Session, *, work_id: str, hidden: bool, organize_status: str, now: Any
) -> None:
    if not _has_table(db, "LibraryWork"):
        return
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(hidden=hidden, organize_status=organize_status, updated_at=now)
    )


def _next_sort_order(db: Session, media_version_id: str) -> int:
    current = db.scalar(
        select(func.max(LibraryVolume.sort_order)).where(
            LibraryVolume.media_version_id == media_version_id
        )
    )
    return int(current or 0) + 1


def merge_media_versions_and_volumes(
    db: Session, *, source_work_id: str, target_work_id: str, now: Any
) -> None:
    """Move every source volume under the target work's singleton media version.

    A source media version is re-parented when the target lacks that media kind.
    When both works have the same kind, source volumes are appended in their
    existing stable order and the now-empty source media version is removed.
    """

    source_versions = db.scalars(
        select(LibraryMediaVersion)
        .where(LibraryMediaVersion.work_id == source_work_id)
        .order_by(
            LibraryMediaVersion.media_kind.asc(),
            LibraryMediaVersion.created_at.asc(),
            LibraryMediaVersion.id.asc(),
        )
    ).all()
    for source_version in source_versions:
        target_version = db.scalar(
            select(LibraryMediaVersion).where(
                LibraryMediaVersion.work_id == target_work_id,
                LibraryMediaVersion.media_kind == source_version.media_kind,
            )
        )
        if target_version is None:
            source_version.work_id = target_work_id
            source_version.updated_at = now
            continue

        next_order = _next_sort_order(db, target_version.id)
        source_volumes = db.scalars(
            select(LibraryVolume)
            .where(LibraryVolume.media_version_id == source_version.id)
            .order_by(
                LibraryVolume.sort_order.asc(),
                LibraryVolume.created_at.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
        for offset, volume in enumerate(source_volumes):
            volume.media_version_id = target_version.id
            volume.sort_order = next_order + offset
            volume.updated_at = now
        db.flush()
        db.delete(source_version)

    if _has_table(db, "ImportTask"):
        db.execute(
            update(ImportTask)
            .where(ImportTask.work_id == source_work_id)
            .values(work_id=target_work_id, updated_at=now)
        )
    if _has_table(db, "MetadataLookupTask"):
        db.execute(
            update(MetadataLookupTask)
            .where(
                MetadataLookupTask.work_id == source_work_id,
                MetadataLookupTask.volume_id.is_not(None),
            )
            .values(work_id=target_work_id, updated_at=now)
        )
