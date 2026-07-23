from __future__ import annotations

import json
from typing import Final

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("zh-CN", "en-US")
DEFAULT_LOCALE: Final[str] = "zh-CN"


def normalize_locale(value: object, *, fallback: str | None = DEFAULT_LOCALE) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate in SUPPORTED_LOCALES:
            return candidate
    return fallback


def configured_locale(db: Session) -> str:
    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("SystemSetting"):
        return DEFAULT_LOCALE
    try:
        row = db.execute(
            text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'language' LIMIT 1")
        ).mappings().first()
    except SQLAlchemyError:
        return DEFAULT_LOCALE
    if row is None:
        return DEFAULT_LOCALE
    raw_value = row.get("value")
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except (TypeError, ValueError):
            decoded = raw_value
    else:
        decoded = raw_value
    return normalize_locale(decoded) or DEFAULT_LOCALE
