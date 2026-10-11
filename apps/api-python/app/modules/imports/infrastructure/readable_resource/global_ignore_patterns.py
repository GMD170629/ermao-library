"""ORM projection for system-wide import ignore patterns."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.setting_values import decode_setting_value
from app.models.settings import SystemSetting
from app.modules.imports.domain.ignore_rules import (
    IMPORT_IGNORE_PATTERNS_KEY,
    normalize_ignore_patterns,
)


def load_global_ignore_patterns(session: Session) -> str:
    raw = session.scalar(
        select(SystemSetting.value).where(
            SystemSetting.key == IMPORT_IGNORE_PATTERNS_KEY
        )
    )
    if raw is None:
        return ""
    value = decode_setting_value(raw)
    return normalize_ignore_patterns(value)


__all__ = ["load_global_ignore_patterns"]
