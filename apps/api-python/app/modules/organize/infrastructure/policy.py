"""ORM persistence for OrganizePolicy."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.organize import OrganizePolicy

DEFAULT_POLICY_ID = "default"
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
DEFAULT_RULES = {
    "unrecognized": True,
    "missingMetadata": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def has_policy_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("OrganizePolicy")


def entity_as_legacy_dict(entity: OrganizePolicy) -> dict[str, Any]:
    """Map an ORM policy to camelCase keys matching legacy raw-SQL row dicts."""

    return {
        "id": entity.id,
        "enabled": entity.enabled,
        "scheduleMode": entity.schedule_mode,
        "intervalMinutes": entity.interval_minutes,
        "autoRunOnNew": entity.auto_run_on_new,
        "autoRunOnNewSince": entity.auto_run_on_new_since,
        "rulesJson": entity.rules_json,
        "overwriteTitleAuthor": entity.overwrite_title_author,
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
        "overwriteTitleAuthor": bool(row.get("overwriteTitleAuthor", True)),
        "lastScheduledAt": row.get("lastScheduledAt"),
        "nextRunAt": row.get("nextRunAt"),
        "updatedAt": row.get("updatedAt"),
    }


def get_policy_row(db: Session, policy_id: str = DEFAULT_POLICY_ID) -> dict[str, Any] | None:
    entity = db.scalar(select(OrganizePolicy).where(OrganizePolicy.id == policy_id))
    return entity_as_legacy_dict(entity) if entity is not None else None


def insert_default_policy_if_missing(db: Session) -> None:
    now = _now()
    db.execute(
        sqlite_insert(OrganizePolicy)
        .values(
            id=DEFAULT_POLICY_ID,
            enabled=False,
            schedule_mode="MANUAL",
            interval_minutes=DEFAULT_INTERVAL_MINUTES,
            auto_run_on_new=False,
            auto_run_on_new_since=None,
            rules_json=json.dumps(DEFAULT_RULES, ensure_ascii=False),
            overwrite_title_author=True,
            last_scheduled_at=None,
            next_run_at=None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[OrganizePolicy.id])
    )


def ensure_organize_policy(db: Session) -> dict[str, Any]:
    if not has_policy_table(db):
        raise ValueError("整理策略数据表尚未初始化")
    existing = get_policy_row(db)
    if existing:
        return policy_view(existing)
    insert_default_policy_if_missing(db)
    db.flush()
    return policy_view(get_policy_row(db) or {})


def get_organize_policy(db: Session) -> dict[str, Any]:
    return ensure_organize_policy(db)


def update_organize_policy(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = ensure_organize_policy(db)
    schedule_mode = str(payload.get("scheduleMode", current["scheduleMode"])).upper()
    if schedule_mode not in {"MANUAL", "INTERVAL"}:
        raise ValueError("执行方式仅支持手动或定时间隔")
    try:
        interval = int(payload.get("intervalMinutes", current["intervalMinutes"]))
    except (TypeError, ValueError):
        raise ValueError("执行间隔格式不正确") from None
    if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
        raise ValueError(f"执行间隔需在 {MIN_INTERVAL_MINUTES} 到 {MAX_INTERVAL_MINUTES} 分钟之间")

    enabled = bool(payload.get("enabled", current["enabled"]))
    auto_run_on_new = bool(payload.get("autoRunOnNew", current["autoRunOnNew"]))
    rules_payload = payload.get("rules", current["rules"])
    if not isinstance(rules_payload, dict):
        raise ValueError("识别范围配置格式不正确")
    rules = {
        "unrecognized": bool(rules_payload.get("unrecognized", current["rules"]["unrecognized"])),
        "missingMetadata": bool(rules_payload.get("missingMetadata", current["rules"]["missingMetadata"])),
    }
    now = _now()
    newly_enabled_for_new = auto_run_on_new and not current["autoRunOnNew"]
    auto_since = now if newly_enabled_for_new else current.get("autoRunOnNewSince")
    if not auto_run_on_new:
        auto_since = None
    next_run_at = None
    if enabled and schedule_mode == "INTERVAL":
        old_next = current.get("nextRunAt")
        settings_changed = (
            not current["enabled"]
            or current["scheduleMode"] != schedule_mode
            or current["intervalMinutes"] != interval
        )
        next_run_at = now + timedelta(minutes=interval) if settings_changed or not old_next else old_next

    db.execute(
        update(OrganizePolicy)
        .where(OrganizePolicy.id == DEFAULT_POLICY_ID)
        .values(
            enabled=enabled,
            schedule_mode=schedule_mode,
            interval_minutes=interval,
            auto_run_on_new=auto_run_on_new,
            auto_run_on_new_since=auto_since,
            rules_json=json.dumps(rules, ensure_ascii=False),
            overwrite_title_author=bool(payload.get("overwriteTitleAuthor", current["overwriteTitleAuthor"])),
            next_run_at=next_run_at,
            updated_at=now,
        )
    )
    db.flush()
    return policy_view(get_policy_row(db) or {})


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
