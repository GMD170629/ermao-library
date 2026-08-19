"""ORM persistence for duplicate candidates and non-structural duplicate actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, delete, func, insert, inspect, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.organize import DuplicateCandidate
from app.modules.organize.application.dto import PreparedDuplicateAction
from app.modules.organize.application.errors import InvalidDuplicateActionError
from app.modules.organize.infrastructure.eligibility import work_entity_as_legacy_dict

ALLOWED_DUPLICATE_ACTIONS = frozenset({"HIDE_DUPLICATE", "KEEP_SEPARATE"})


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
    """Build hide/keep mutations before the write UoW. Structural merge is rejected."""

    del db
    for action in actions:
        if action.action not in ALLOWED_DUPLICATE_ACTIONS:
            raise InvalidDuplicateActionError(action.action)

    statements: list[PreparedDuplicateStatement] = []
    hidden_rows = tuple(
        {
            "id": action.source_work_id,
            "hidden": True,
            "organize_status": "APPLIED",
            "updated_at": action.timestamp,
        }
        for action in actions
        if action.action == "HIDE_DUPLICATE"
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
        "mediaVersionId": entity.version_id,
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


def dismiss_pending_duplicates_for_jobs(db: Session, job_ids: tuple[str, ...]) -> None:
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


def insert_duplicate_candidates(db: Session, rows: tuple[dict[str, Any], ...]) -> None:
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
            LibraryMediaVersion.id == LibraryVolume.version_id,
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
