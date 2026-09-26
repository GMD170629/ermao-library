"""Bounded recognition results in the existing per-book lookup-task records."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.organize import MetadataLookupTask
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.application.recognition import candidate_summary, match_view
from app.modules.metadata.domain.recognition import (
    MatchDecision,
    RecognitionContext,
    recognition_fingerprint,
)


def save_recognition_record(db: Session, context: RecognitionContext, source_node_id: str, provider: str,
                            assessed: list[tuple[dict[str, Any], MatchDecision]], query: str) -> str:
    identifier = "recognition-" + uuid4().hex
    outcome = "MATCHED_UNAPPLIED" if any(decision.outcome == "MATCHED" for _, decision in assessed) else "AMBIGUOUS" if any(decision.outcome == "AMBIGUOUS" for _, decision in assessed) else "NO_MATCH"
    payload = {"recognition": {"schemaVersion": 3, "execution": "MANUAL", "outcome": outcome,
        "fingerprint": recognition_fingerprint(context), "targetType": context.target_type, "targetId": context.target_id,
        "revision": context.revision, "relatedRevision": context.related_revision, "configRevision": context.config_revision,
        "sourceNodeId": source_node_id, "query": query[:500]},
        "attempted": [{"provider": provider, "candidates": [candidate_summary(value) for value, _ in assessed[:10]],
                       "matches": [match_view(decision) for _, decision in assessed[:10]]}]}
    db.close()
    with MetadataWriteTransaction(db):
        db.add(MetadataLookupTask(id=identifier, book_id=context.book_id, resource_id=context.resource_id,
            status="NO_MATCH", provider_order=json.dumps([provider]), candidate_raw_json=json.dumps(payload, ensure_ascii=False),
            result_source=provider, attempts=0, finished_at=datetime.now(UTC)))
    return identifier


def recognition_record(db: Session, book_id: str, record_id: str) -> dict[str, Any] | None:
    row = db.get(MetadataLookupTask, record_id, populate_existing=True)
    if row is None or row.book_id != book_id:
        return None
    raw = json.loads(row.candidate_raw_json or "{}")
    if not isinstance(raw, dict) or not isinstance(raw.get("recognition"), dict):
        return None
    return raw


def ignore_recognition_record(db: Session, book_id: str, record_id: str) -> bool:
    raw = recognition_record(db, book_id, record_id)
    if raw is None:
        return False
    raw["recognition"]["ignored"] = True
    row = db.get(MetadataLookupTask, record_id)
    if row is None:
        return False
    row.candidate_raw_json = json.dumps(raw, ensure_ascii=False)
    db.flush()
    return True


def complete_recognition_record(db: Session, book_id: str, record_id: str, candidate: dict[str, Any], fields: list[str],
                                context: RecognitionContext, *, changed: bool = True) -> None:
    raw = recognition_record(db, book_id, record_id)
    row = db.get(MetadataLookupTask, record_id)
    if raw is None or row is None:
        raise ValueError("RECOGNITION_RECORD_MISSING")
    raw["selected"] = candidate_summary(candidate)
    raw["recognition"].update(outcome="APPLIED" if changed else "NO_CHANGES", humanConfirmed=True,
        confirmedRevision=context.revision, confirmedRelatedRevision=context.related_revision,
        appliedSelection=fields)
    row.candidate_raw_json = json.dumps(raw, ensure_ascii=False)
    row.applied_fields = json.dumps(fields)
    row.status = "COMPLETED"
    row.finished_at = datetime.now(UTC)
    db.flush()
