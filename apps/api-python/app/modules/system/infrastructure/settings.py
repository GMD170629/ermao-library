"""ORM persistence for SystemSetting key-value storage."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.settings import SystemSetting


def _serialize_setting_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_setting_value(raw: Any, fallback: Any = None) -> Any:
    if raw is None:
        return fallback
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    text = str(raw)
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text if text else fallback


def get_setting_raw(db: Session, key: str) -> str | None:
    value = db.scalar(select(SystemSetting.value).where(SystemSetting.key == key))
    return None if value is None else str(value)


def get_settings_raw(db: Session, keys: list[str]) -> dict[str, str | None]:
    if not keys:
        return {}
    rows = db.execute(select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(keys))).all()
    found = {str(key): None if value is None else str(value) for key, value in rows}
    return {key: found.get(key) for key in keys}


def get_setting(db: Session, key: str, fallback: Any = None) -> Any:
    raw = get_setting_raw(db, key)
    if raw is None:
        return fallback
    return parse_setting_value(raw, fallback)


def list_settings(db: Session) -> dict[str, Any]:
    rows = db.execute(select(SystemSetting.key, SystemSetting.value)).all()
    return {str(key): parse_setting_value(value, value) for key, value in rows}


def upsert_setting(db: Session, key: str, value: Any) -> None:
    now = db_timestamp()
    serialized = _serialize_setting_value(value)
    statement = (
        sqlite_insert(SystemSetting)
        .values(key=key, value=serialized, created_at=now, updated_at=now)
        .on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={
                SystemSetting.value: serialized,
                SystemSetting.updated_at: now,
            },
        )
    )
    db.execute(statement)


def upsert_settings(db: Session, values: dict[str, Any]) -> None:
    for key, value in values.items():
        upsert_setting(db, key, value)


def delete_setting(db: Session, key: str) -> None:
    db.execute(delete(SystemSetting).where(SystemSetting.key == key))


def delete_settings(db: Session, keys: set[str] | list[str]) -> None:
    key_list = list(keys)
    if not key_list:
        return
    db.execute(delete(SystemSetting).where(SystemSetting.key.in_(key_list)))


def existing_setting_keys(db: Session, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    return set(db.scalars(select(SystemSetting.key).where(SystemSetting.key.in_(keys))).all())
