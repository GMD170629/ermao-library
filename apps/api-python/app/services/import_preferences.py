from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.imports.application.audio_types import SUPPORTED_AUDIO_EXTS
from app.modules.imports.domain.ignore_rules import (
    IMPORT_IGNORE_PATTERNS_KEY,
    matches_configured_ignore_patterns,
    normalize_ignore_patterns,
)

IMPORT_ALLOWED_EXTENSIONS_KEY = "import.allowedExtensions"
IMPORT_PREFERENCE_KEYS = {
    IMPORT_ALLOWED_EXTENSIONS_KEY,
    IMPORT_IGNORE_PATTERNS_KEY,
}

SUPPORTED_IMPORT_EXTENSIONS = (
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".prc",
    ".fb2",
    ".txt",
    ".pdf",
    ".cbz",
    ".cbr",
    ".zip",
    ".rar",
    *sorted(SUPPORTED_AUDIO_EXTS),
)


@dataclass(frozen=True)
class ImportPreferences:
    allowed_extensions: tuple[str, ...] = SUPPORTED_IMPORT_EXTENSIONS
    ignore_patterns: str = ""


@dataclass(frozen=True, slots=True)
class RawImportPreferencesProjection:
    """Unparsed values copied directly from the settings query."""

    available: bool
    rows: tuple[tuple[str, str | None], ...] = ()


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def normalize_allowed_extensions(value: Any) -> tuple[str, ...]:
    value = _json_value(value)
    if value is None:
        return SUPPORTED_IMPORT_EXTENSIONS
    if not isinstance(value, (list, tuple, set)):
        return SUPPORTED_IMPORT_EXTENSIONS
    requested = {
        f".{str(item).strip().lower().lstrip('.')}"
        for item in value
        if str(item).strip()
    }
    return tuple(
        extension for extension in SUPPORTED_IMPORT_EXTENSIONS if extension in requested
    )


def normalize_import_setting_value(key: str, value: Any) -> Any:
    if key == IMPORT_ALLOWED_EXTENSIONS_KEY:
        return list(normalize_allowed_extensions(value))
    if key == IMPORT_IGNORE_PATTERNS_KEY:
        return normalize_ignore_patterns(_json_value(value))
    return value


def load_raw_import_preferences_projection(
    db: Session,
) -> RawImportPreferencesProjection:
    """Read only raw preference columns; parsing belongs after Session release."""

    try:
        rows = db.execute(
            select(SystemSetting.key, SystemSetting.value).where(
                SystemSetting.key.in_(IMPORT_PREFERENCE_KEYS)
            )
        ).all()
        copied_rows = tuple(
            (str(key), None if value is None else str(value)) for key, value in rows
        )
    except SQLAlchemyError:
        return RawImportPreferencesProjection(available=False)
    return RawImportPreferencesProjection(available=True, rows=copied_rows)


def prepare_import_preferences(
    projection: RawImportPreferencesProjection,
) -> ImportPreferences:
    """Parse and normalize a raw projection without a database dependency."""

    if not projection.available:
        return ImportPreferences()
    values = dict(projection.rows)
    return ImportPreferences(
        allowed_extensions=normalize_allowed_extensions(
            values.get(IMPORT_ALLOWED_EXTENSIONS_KEY)
        ),
        ignore_patterns=normalize_ignore_patterns(
            _json_value(values.get(IMPORT_IGNORE_PATTERNS_KEY))
        ),
    )


def matches_ignore_patterns(path: str | Path, patterns: str | None) -> bool:
    return matches_configured_ignore_patterns(path, patterns)


def extension_is_allowed(path: str | Path, preferences: ImportPreferences) -> bool:
    candidate = Path(path)
    return (
        candidate.is_dir() or candidate.suffix.lower() in preferences.allowed_extensions
    )
