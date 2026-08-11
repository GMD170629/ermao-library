"""ORM persistence for duplicate candidates and work merge actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, delete, func, insert, inspect, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.import_pipeline import ImportTask
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.organize import DuplicateCandidate, MetadataLookupTask
from app.modules.organize.application.dto import PreparedDuplicateAction
from app.modules.organize.infrastructure.eligibility import work_entity_as_legacy_dict


@dataclass(frozen=True, slots=True)
class PreparedDuplicateStatement:
    statement: Executable
    parameters: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedDuplicateWrite:
    statements: tuple[PreparedDuplicateStatement, ...]


def prepare_duplicate_actions_write(
    db: Session,
    actions: tuple[PreparedDuplicateAction, ...],
) -> PreparedDuplicateWrite:
    """Load merge projections and build every mutation before the write UoW."""

    merge_actions = tuple(action for action in actions if action.action == "MERGE_WORKS")
    source_ids = tuple(dict.fromkeys(action.source_work_id for action in merge_actions))
    target_ids = tuple(dict.fromkeys(action.target_work_id for action in merge_actions))
    all_work_ids = source_ids + tuple(
        work_id for work_id in target_ids if work_id not in source_ids
    )
    version_rows = (
        tuple(
            db.execute(
                select(
                    LibraryMediaVersion.id,
                    LibraryMediaVersion.work_id,
                    LibraryMediaVersion.media_kind,
                    LibraryMediaVersion.created_at,
                )
                .where(LibraryMediaVersion.work_id.in_(all_work_ids))
                .order_by(
                    LibraryMediaVersion.created_at.asc(),
                    LibraryMediaVersion.id.asc(),
                )
            ).all()
        )
        if all_work_ids
        else ()
    )
    version_ids = tuple(str(row.id) for row in version_rows)
    volume_rows = (
        tuple(
            db.execute(
                select(
                    LibraryVolume.id,
                    LibraryVolume.media_version_id,
                    LibraryVolume.sort_order,
                    LibraryVolume.created_at,
                )
                .where(LibraryVolume.media_version_id.in_(version_ids))
                .order_by(
                    LibraryVolume.sort_order.asc(),
                    LibraryVolume.created_at.asc(),
                    LibraryVolume.id.asc(),
                )
            ).all()
        )
        if version_ids
        else ()
    )
    versions_by_work: dict[str, list[object]] = {}
    target_by_kind: dict[tuple[str, str], str] = {}
    for row in version_rows:
        versions_by_work.setdefault(str(row.work_id), []).append(row)
        target_by_kind[(str(row.work_id), str(row.media_kind))] = str(row.id)
    volumes_by_version: dict[str, list[object]] = {}
    next_order_by_version: dict[str, int] = {}
    for row in volume_rows:
        version_id = str(row.media_version_id)
        volumes_by_version.setdefault(version_id, []).append(row)
        next_order_by_version[version_id] = max(
            next_order_by_version.get(version_id, 0), int(row.sort_order or 0) + 1
        )

    reparent_versions: list[dict[str, object]] = []
    move_volumes: list[dict[str, object]] = []
    delete_version_ids: list[str] = []
    merge_work_targets: dict[str, str] = {}
    for action in merge_actions:
        merge_work_targets[action.source_work_id] = action.target_work_id
        for source_version in versions_by_work.get(action.source_work_id, []):
            source_version_id = str(source_version.id)
            key = (action.target_work_id, str(source_version.media_kind))
            target_version_id = target_by_kind.get(key)
            if target_version_id is None:
                reparent_versions.append(
                    {
                        "id": source_version_id,
                        "work_id": action.target_work_id,
                        "updated_at": action.timestamp,
                    }
                )
                target_by_kind[key] = source_version_id
                continue
            next_order = next_order_by_version.get(target_version_id, 0)
            source_volumes = volumes_by_version.get(source_version_id, [])
            move_volumes.extend(
                {
                    "id": str(volume.id),
                    "media_version_id": target_version_id,
                    "sort_order": next_order + offset,
                    "updated_at": action.timestamp,
                }
                for offset, volume in enumerate(source_volumes)
            )
            next_order_by_version[target_version_id] = next_order + len(source_volumes)
            delete_version_ids.append(source_version_id)

    statements: list[PreparedDuplicateStatement] = []
    for chunk in sqlite_parameter_chunks(
        tuple(reparent_versions), parameters_per_row=3
    ):
        statements.append(
            PreparedDuplicateStatement(update(LibraryMediaVersion), tuple(chunk))
        )
    for chunk in sqlite_parameter_chunks(tuple(move_volumes), parameters_per_row=4):
        statements.append(
            PreparedDuplicateStatement(update(LibraryVolume), tuple(chunk))
        )
    if delete_version_ids:
        statements.append(
            PreparedDuplicateStatement(
                delete(LibraryMediaVersion).where(
                    LibraryMediaVersion.id.in_(tuple(delete_version_ids))
                )
            )
        )
    if merge_work_targets and _has_table(db, "ImportTask"):
        statements.append(
            PreparedDuplicateStatement(
                update(ImportTask)
                .where(ImportTask.work_id.in_(tuple(merge_work_targets)))
                .values(
                    work_id=case(merge_work_targets, value=ImportTask.work_id),
                    updated_at=merge_actions[0].timestamp,
                )
            )
        )
    if merge_work_targets and _has_table(db, "MetadataLookupTask"):
        statements.append(
            PreparedDuplicateStatement(
                update(MetadataLookupTask)
                .where(
                    MetadataLookupTask.work_id.in_(tuple(merge_work_targets)),
                    MetadataLookupTask.volume_id.is_not(None),
                )
                .values(
                    work_id=case(
                        merge_work_targets, value=MetadataLookupTask.work_id
                    ),
                    updated_at=merge_actions[0].timestamp,
                )
            )
        )
    hidden_rows = tuple(
        {
            "id": action.source_work_id,
            "hidden": True,
            "organize_status": "APPLIED",
            "updated_at": action.timestamp,
        }
        for action in actions
        if action.action in {"HIDE_DUPLICATE", "MERGE_WORKS"}
    )
    for chunk in sqlite_parameter_chunks(hidden_rows, parameters_per_row=4):
        statements.append(PreparedDuplicateStatement(update(LibraryWork), tuple(chunk)))
    duplicate_rows = tuple(
        {"id": action.duplicate_id, "status": "APPLIED", "updated_at": action.timestamp}
        for action in actions
        if action.duplicate_id
    )
    for chunk in sqlite_parameter_chunks(duplicate_rows, parameters_per_row=3):
        statements.append(
            PreparedDuplicateStatement(update(DuplicateCandidate), tuple(chunk))
        )
    return PreparedDuplicateWrite(tuple(statements))


def prepare_work_merge_write(
    db: Session,
    *,
    source_work_id: str,
    target_work_id: str,
    timestamp: Any,
) -> PreparedDuplicateWrite:
    return prepare_duplicate_actions_write(
        db,
        (
            PreparedDuplicateAction(
                duplicate_id="",
                source_work_id=source_work_id,
                target_work_id=target_work_id,
                action="MERGE_WORKS",
                timestamp=timestamp,
            ),
        ),
    )


def execute_duplicate_actions_write(
    db: Session, prepared: PreparedDuplicateWrite
) -> None:
    for item in prepared.statements:
        if item.parameters:
            db.execute(item.statement, list(item.parameters))
        else:
            db.execute(item.statement)


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


def dismiss_pending_duplicates_for_jobs(
    db: Session, job_ids: tuple[str, ...]
) -> None:
    if not job_ids or not _has_table(db, "DuplicateCandidate"):
        return
    db.execute(
        update(DuplicateCandidate)
        .where(
            DuplicateCandidate.job_id.in_(job_ids),
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
    db.execute(
        insert(DuplicateCandidate).values(
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


def insert_duplicate_candidates(
    db: Session, rows: tuple[dict[str, Any], ...]
) -> None:
    """Insert a prepared duplicate-candidate batch in one typed statement."""
    if not rows:
        return
    db.execute(insert(DuplicateCandidate), rows)


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
