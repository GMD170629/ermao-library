"""ORM persistence for MetadataSuggestion review rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.models.organize import MetadataSuggestion


def suggestion_entity_record(entity: MetadataSuggestion) -> dict[str, Any]:
    return {
        "id": entity.id,
        "jobId": entity.job_id,
        "field": entity.field,
        "currentValue": entity.current_value,
        "suggestedValue": entity.suggested_value,
        "source": entity.source,
        "confidence": entity.confidence,
        "reason": entity.reason,
        "status": entity.status,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def list_pending_suggestions(db: Session, job_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MetadataSuggestion).where(
            MetadataSuggestion.job_id == job_id,
            MetadataSuggestion.status == "PENDING",
        )
    ).all()
    return [suggestion_entity_record(row) for row in rows]


def list_suggestion_dedupe_keys(db: Session, job_id: str) -> set[str]:
    rows = db.execute(
        select(
            MetadataSuggestion.field,
            MetadataSuggestion.source,
            MetadataSuggestion.suggested_value,
        ).where(MetadataSuggestion.job_id == job_id)
    ).all()
    return {f"{field}:{source}:{suggested}" for field, source, suggested in rows}


def insert_suggestion(
    db: Session,
    *,
    suggestion_id: str,
    job_id: str,
    field: str,
    current_value: Any,
    suggested_value: Any,
    source: str,
    confidence: float,
    reason: str,
    status: str,
    now: Any,
) -> None:
    db.execute(
        insert(MetadataSuggestion).values(
            id=suggestion_id,
            job_id=job_id,
            field=field,
            current_value=None if current_value is None else str(current_value),
            suggested_value=str(suggested_value),
            source=source,
            confidence=float(confidence),
            reason=str(reason),
            status=status,
            created_at=now,
            updated_at=now,
        )
    )


def insert_suggestions(db: Session, rows: tuple[dict[str, Any], ...]) -> None:
    """Insert a prepared suggestion batch without per-row ORM flushes."""
    if not rows:
        return
    db.execute(insert(MetadataSuggestion), rows)


def mark_suggestions_applied(db: Session, suggestion_ids: list[str]) -> None:
    if not suggestion_ids:
        return
    db.execute(
        update(MetadataSuggestion)
        .where(MetadataSuggestion.id.in_(suggestion_ids))
        .values(status="APPLIED")
    )


def dismiss_pending_suggestions(db: Session, job_id: str) -> None:
    db.execute(
        update(MetadataSuggestion)
        .where(
            MetadataSuggestion.job_id == job_id,
            MetadataSuggestion.status == "PENDING",
        )
        .values(status="DISMISSED")
    )


def dismiss_pending_suggestions_for_jobs(
    db: Session, job_ids: tuple[str, ...]
) -> None:
    if not job_ids:
        return
    db.execute(
        update(MetadataSuggestion)
        .where(
            MetadataSuggestion.job_id.in_(job_ids),
            MetadataSuggestion.status == "PENDING",
        )
        .values(status="DISMISSED")
    )
