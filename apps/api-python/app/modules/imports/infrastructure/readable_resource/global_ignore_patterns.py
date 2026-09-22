"""ORM projection for system-wide import ignore patterns."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exception_diagnostics import record_exception
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
    try:
        value: object = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        record_exception(logging.getLogger(__name__), "modules.imports.infrastructure.readable_resource.global_ignore_patterns.load_global_ignore_patterns.failed", error,
                         context={"step": "load_global_ignore_patterns"})
        value = str(raw)
    return normalize_ignore_patterns(value)


__all__ = ["load_global_ignore_patterns"]
