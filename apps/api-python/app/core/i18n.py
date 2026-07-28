from __future__ import annotations

from typing import Final

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.system.infrastructure.settings import get_setting


SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("zh-CN", "en-US")
DEFAULT_LOCALE: Final[str] = "zh-CN"


def normalize_locale(value: object, *, fallback: str | None = DEFAULT_LOCALE) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate in SUPPORTED_LOCALES:
            return candidate
    return fallback


def configured_locale(db: Session) -> str:
    try:
        value = get_setting(db, "language", fallback=DEFAULT_LOCALE)
    except SQLAlchemyError:
        return DEFAULT_LOCALE
    return normalize_locale(value) or DEFAULT_LOCALE
