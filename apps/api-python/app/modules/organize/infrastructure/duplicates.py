"""ORM persistence for DuplicateCandidate and organize merge actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import DuplicateCandidate
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


def edition_entity_as_legacy_dict(entity: LibraryEdition) -> dict[str, Any]:
    return {
        "id": entity.id,
        "workId": entity.work_id,
        "monitorFolderId": entity.monitor_folder_id,
        "origin": entity.origin,
        "mediaKind": entity.media_kind,
        "format": entity.format,
        "versionName": entity.version_name,
        "versionKey": entity.version_key,
        "sourceGroupKey": entity.source_group_key,
        "description": entity.description,
        "language": entity.language,
        "publisher": entity.publisher,
        "publishedAt": entity.published_at,
        "identifier": entity.identifier,
        "isbn": entity.isbn,
        "importStatus": entity.import_status,
        "importError": entity.import_error,
        "sizeBytes": entity.size_bytes,
        "pageCount": entity.page_count,
        "chapterCount": entity.chapter_count,
        "durationMs": entity.duration_ms,
        "trackCount": entity.track_count,
        "narrator": entity.narrator,
        "abridged": entity.abridged,
        "coverPath": entity.cover_path,
        "coverStatus": entity.cover_status,
        "primary": entity.is_primary,
        "hidden": entity.hidden,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def list_duplicates_by_ids(db: Session, *, job_id: str, duplicate_ids: list[str]) -> list[dict[str, Any]]:
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
        select(LibraryWork).where(LibraryWork.id != work_id, LibraryWork.hidden.is_(False))
    ).all()
    return [work_entity_as_legacy_dict(row) for row in rows]


def first_visible_edition(db: Session, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryEdition"):
        return None
    entity = db.scalars(
        select(LibraryEdition)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, False).is_(False),
        )
        .order_by(func.coalesce(LibraryEdition.is_primary, False).desc(), LibraryEdition.created_at.asc())
        .limit(1)
    ).first()
    return edition_entity_as_legacy_dict(entity) if entity is not None else None


def get_edition_for_work(db: Session, *, edition_id: str, work_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "LibraryEdition"):
        return None
    entity = db.scalar(
        select(LibraryEdition).where(LibraryEdition.id == edition_id, LibraryEdition.work_id == work_id)
    )
    return edition_entity_as_legacy_dict(entity) if entity is not None else None


def set_work_hidden(db: Session, *, work_id: str, hidden: bool, organize_status: str, now: Any) -> None:
    if not _has_table(db, "LibraryWork"):
        return
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(hidden=hidden, organize_status=organize_status, updated_at=now)
    )


def set_work_primary_edition(db: Session, *, work_id: str, edition_id: str, now: Any) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(primary_edition_id=edition_id, updated_at=now)
    )
    if _has_table(db, "LibraryEdition"):
        db.execute(
            update(LibraryEdition)
            .where(LibraryEdition.id == edition_id)
            .values(is_primary=True, updated_at=now)
        )


def merge_editions_as_version(db: Session, *, source_work_id: str, target_work_id: str, now: Any) -> None:
    if _has_table(db, "LibraryEdition"):
        db.execute(
            update(LibraryEdition)
            .where(LibraryEdition.work_id == source_work_id)
            .values(work_id=target_work_id, is_primary=False, updated_at=now)
        )
    if _has_table(db, "ImportTask"):
        db.execute(
            update(ImportTask)
            .where(ImportTask.work_id == source_work_id)
            .values(work_id=target_work_id, updated_at=now)
        )
    if _has_table(db, "LibraryReadingProgress"):
        db.execute(
            update(LibraryReadingProgress)
            .where(LibraryReadingProgress.work_id == source_work_id)
            .values(work_id=target_work_id, updated_at=now)
        )


def list_editions_for_work(db: Session, work_id: str) -> list[dict[str, Any]]:
    if not _has_table(db, "LibraryEdition"):
        return []
    rows = db.scalars(select(LibraryEdition).where(LibraryEdition.work_id == work_id)).all()
    return [edition_entity_as_legacy_dict(row) for row in rows]


def merge_edition_as_volume(
    db: Session,
    *,
    source_edition_id: str,
    target_edition_id: str,
    target_work_id: str,
    now: Any,
) -> None:
    if _has_table(db, "LibraryVolume"):
        db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.edition_id == source_edition_id)
            .values(edition_id=target_edition_id, updated_at=now)
        )
    if _has_table(db, "LibraryFile"):
        db.execute(
            update(LibraryFile)
            .where(LibraryFile.edition_id == source_edition_id)
            .values(edition_id=target_edition_id, updated_at=now)
        )
    if _has_table(db, "LibraryReadingUnit"):
        db.execute(
            update(LibraryReadingUnit)
            .where(LibraryReadingUnit.edition_id == source_edition_id)
            .values(edition_id=target_edition_id, updated_at=now)
        )
    if _has_table(db, "LibraryMetadata"):
        db.execute(
            update(LibraryMetadata)
            .where(LibraryMetadata.edition_id == source_edition_id)
            .values(edition_id=target_edition_id, updated_at=now)
        )
    if _has_table(db, "ImportTask"):
        db.execute(
            update(ImportTask)
            .where(ImportTask.edition_id == source_edition_id)
            .values(work_id=target_work_id, edition_id=target_edition_id, updated_at=now)
        )
    db.execute(
        update(LibraryEdition)
        .where(LibraryEdition.id == source_edition_id)
        .values(hidden=True, updated_at=now)
    )


def retarget_progress_to_edition(
    db: Session,
    *,
    source_work_id: str,
    target_work_id: str,
    target_edition_id: str,
    now: Any,
) -> None:
    if not _has_table(db, "LibraryReadingProgress"):
        return
    db.execute(
        update(LibraryReadingProgress)
        .where(LibraryReadingProgress.work_id == source_work_id)
        .values(work_id=target_work_id, edition_id=target_edition_id, updated_at=now)
    )
