"""ORM persistence for OrganizePolicy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    validate_local_metadata_priority,
)
from app.models.organize import OrganizePolicy
from app.modules.organize.application.dto import PreparedOrganizePolicyUpdate

DEFAULT_POLICY_ID = "default"
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
DEFAULT_RULES = {
    "unrecognized": True,
    "missingMetadata": True,
}
DEFAULT_POLICY_UPDATED_AT = datetime(1970, 1, 1, tzinfo=UTC)


def has_policy_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("OrganizePolicy")


def entity_record(entity: OrganizePolicy) -> dict[str, Any]:
    """Map an ORM policy to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": entity.id,
        "enabled": entity.enabled,
        "scheduleMode": entity.schedule_mode,
        "intervalMinutes": entity.interval_minutes,
        "autoRunOnNew": entity.auto_run_on_new,
        "autoRunOnNewSince": entity.auto_run_on_new_since,
        "rulesJson": entity.rules_json,
        "writeMetadataToFiles": entity.write_metadata_to_files,
        "preferLocalMetadata": entity.prefer_local_metadata,
        "localMetadataPriorityJson": entity.local_metadata_priority_json,
        "lastScheduledAt": entity.last_scheduled_at,
        "nextRunAt": entity.next_run_at,
        "createdAt": entity.created_at,
        "updatedAt": entity.updated_at,
    }


def _json_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(fallback)
    return parsed if isinstance(parsed, dict) else dict(fallback)


def policy_view(row: dict[str, Any]) -> dict[str, Any]:
    stored_rules = _json_dict(row.get("rulesJson"), DEFAULT_RULES)
    return {
        "id": row.get("id") or DEFAULT_POLICY_ID,
        "enabled": bool(row.get("enabled")),
        "scheduleMode": str(row.get("scheduleMode") or "MANUAL"),
        "intervalMinutes": int(row.get("intervalMinutes") or DEFAULT_INTERVAL_MINUTES),
        "autoRunOnNew": bool(row.get("autoRunOnNew")),
        "autoRunOnNewSince": row.get("autoRunOnNewSince"),
        "rules": {
            "unrecognized": bool(stored_rules.get("unrecognized", True)),
            "missingMetadata": bool(stored_rules.get("missingMetadata", True)),
        },
        "writeMetadataToFiles": bool(row.get("writeMetadataToFiles", False)),
        "preferLocalMetadata": bool(row.get("preferLocalMetadata", True)),
        "localMetadataPriority": list(
            _stored_local_metadata_priority(row.get("localMetadataPriorityJson"))
        ),
        "lastScheduledAt": row.get("lastScheduledAt"),
        "nextRunAt": row.get("nextRunAt"),
        "updatedAt": row.get("updatedAt") or DEFAULT_POLICY_UPDATED_AT,
    }


def get_policy_row(
    db: Session, policy_id: str = DEFAULT_POLICY_ID
) -> dict[str, Any] | None:
    entity = db.scalar(select(OrganizePolicy).where(OrganizePolicy.id == policy_id))
    return entity_record(entity) if entity is not None else None


def ensure_organize_policy(db: Session) -> dict[str, Any]:
    if not has_policy_table(db):
        raise ValueError("整理策略数据表尚未初始化")
    existing = get_policy_row(db)
    return policy_view(existing or {})


def get_organize_policy(db: Session) -> dict[str, Any]:
    return ensure_organize_policy(db)


def prepare_organize_policy_update_statement(
    prepared: PreparedOrganizePolicyUpdate,
) -> Executable:
    values = {
        "id": DEFAULT_POLICY_ID,
        "enabled": prepared.enabled,
        "schedule_mode": prepared.schedule_mode,
        "interval_minutes": prepared.interval_minutes,
        "auto_run_on_new": prepared.auto_run_on_new,
        "auto_run_on_new_since": prepared.auto_run_on_new_since,
        "rules_json": prepared.rules_json,
        "write_metadata_to_files": prepared.write_metadata_to_files,
        "prefer_local_metadata": prepared.prefer_local_metadata,
        "local_metadata_priority_json": prepared.local_metadata_priority_json,
        "last_scheduled_at": None,
        "next_run_at": prepared.next_run_at,
        "created_at": prepared.updated_at,
        "updated_at": prepared.updated_at,
    }
    statement = sqlite_insert(OrganizePolicy).values(**values)
    return statement.on_conflict_do_update(
        index_elements=[OrganizePolicy.id],
        set_={
            OrganizePolicy.enabled: prepared.enabled,
            OrganizePolicy.schedule_mode: prepared.schedule_mode,
            OrganizePolicy.interval_minutes: prepared.interval_minutes,
            OrganizePolicy.auto_run_on_new: prepared.auto_run_on_new,
            OrganizePolicy.auto_run_on_new_since: prepared.auto_run_on_new_since,
            OrganizePolicy.rules_json: prepared.rules_json,
            OrganizePolicy.write_metadata_to_files: (prepared.write_metadata_to_files),
            OrganizePolicy.prefer_local_metadata: prepared.prefer_local_metadata,
            OrganizePolicy.local_metadata_priority_json: (
                prepared.local_metadata_priority_json
            ),
            OrganizePolicy.next_run_at: prepared.next_run_at,
            OrganizePolicy.updated_at: prepared.updated_at,
        },
    )


def write_prepared_organize_policy_update(db: Session, statement: Executable) -> None:
    db.execute(statement)


def _json_list(value: Any, fallback: list[str]) -> list[object]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return list(fallback)
    return parsed if isinstance(parsed, list) else list(fallback)


def _stored_local_metadata_priority(value: object) -> tuple[str, ...]:
    try:
        return validate_local_metadata_priority(
            _json_list(value, list(DEFAULT_LOCAL_METADATA_PRIORITY))
        )
    except (TypeError, ValueError):
        return DEFAULT_LOCAL_METADATA_PRIORITY


def mark_policy_scheduled(
    db: Session,
    *,
    now: datetime,
    next_run_at: datetime,
    policy_id: str = DEFAULT_POLICY_ID,
) -> None:
    db.execute(
        update(OrganizePolicy)
        .where(OrganizePolicy.id == policy_id)
        .values(
            last_scheduled_at=now,
            next_run_at=next_run_at,
            updated_at=now,
        )
    )
