from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.imports.application.audio_types import SUPPORTED_AUDIO_EXTS

IMPORT_STABILITY_ENABLED_KEY = "import.stabilityCheck.enabled"
IMPORT_STABILITY_SECONDS_KEY = "import.stabilityCheck.seconds"
IMPORT_AUTO_CONVERT_KEY = "import.autoConvertToEpub"
IMPORT_ALLOWED_EXTENSIONS_KEY = "import.allowedExtensions"
IMPORT_IGNORE_PATTERNS_KEY = "import.ignorePatterns"
IMPORT_PREFERENCE_KEYS = {
    IMPORT_STABILITY_ENABLED_KEY,
    IMPORT_STABILITY_SECONDS_KEY,
    IMPORT_AUTO_CONVERT_KEY,
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
DEFAULT_STABILITY_SECONDS = 2.0
MAX_STABILITY_SECONDS = 300.0
DEFAULT_STABILITY_CHECK_ENABLED = False


@dataclass(frozen=True)
class ImportPreferences:
    stability_check_enabled: bool = DEFAULT_STABILITY_CHECK_ENABLED
    stability_check_seconds: float = DEFAULT_STABILITY_SECONDS
    auto_convert_to_epub: bool = True
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


def _boolean(value: Any, default: bool) -> bool:
    value = _json_value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in {"true", "1", "yes", "on"}:
            return True
        if value.strip().lower() in {"false", "0", "no", "off"}:
            return False
    return default


def normalize_stability_seconds(value: Any) -> float:
    value = _json_value(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_STABILITY_SECONDS
    return min(MAX_STABILITY_SECONDS, max(0.5, parsed))


def default_stability_seconds(legacy_delay_ms: str | None = None) -> float:
    if legacy_delay_ms is None:
        legacy_delay_ms = os.environ.get("MONITOR_FILE_STABLE_DELAY_MS")
    if not legacy_delay_ms:
        return DEFAULT_STABILITY_SECONDS
    try:
        return normalize_stability_seconds(float(legacy_delay_ms) / 1000)
    except ValueError:
        return DEFAULT_STABILITY_SECONDS


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
    return tuple(extension for extension in SUPPORTED_IMPORT_EXTENSIONS if extension in requested)


def normalize_ignore_patterns(value: Any) -> str:
    value = _json_value(value)
    if not isinstance(value, str):
        return ""
    patterns = [line.strip() for line in value.replace("\r\n", "\n").split("\n") if line.strip()]
    return "\n".join(patterns[:200])


def normalize_import_setting_value(key: str, value: Any) -> Any:
    if key == IMPORT_STABILITY_ENABLED_KEY:
        return _boolean(value, DEFAULT_STABILITY_CHECK_ENABLED)
    if key == IMPORT_STABILITY_SECONDS_KEY:
        return normalize_stability_seconds(value)
    if key == IMPORT_AUTO_CONVERT_KEY:
        return _boolean(value, True)
    if key == IMPORT_ALLOWED_EXTENSIONS_KEY:
        return list(normalize_allowed_extensions(value))
    if key == IMPORT_IGNORE_PATTERNS_KEY:
        return normalize_ignore_patterns(value)
    return value


def load_raw_import_preferences_projection(
    db: Session,
) -> RawImportPreferencesProjection:
    """Read only raw preference columns; parsing belongs after Session release."""

    try:
        if "SystemSetting" not in inspect(db.connection()).get_table_names():
            return RawImportPreferencesProjection(available=False)
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
    *,
    legacy_stable_delay_ms: str | None,
) -> ImportPreferences:
    """Parse and normalize a raw projection without a database dependency."""

    if not projection.available:
        return ImportPreferences()
    values = dict(projection.rows)
    return ImportPreferences(
        stability_check_enabled=_boolean(
            values.get(IMPORT_STABILITY_ENABLED_KEY),
            DEFAULT_STABILITY_CHECK_ENABLED,
        ),
        stability_check_seconds=(
            normalize_stability_seconds(values[IMPORT_STABILITY_SECONDS_KEY])
            if IMPORT_STABILITY_SECONDS_KEY in values
            else default_stability_seconds(legacy_stable_delay_ms)
        ),
        auto_convert_to_epub=_boolean(values.get(IMPORT_AUTO_CONVERT_KEY), True),
        allowed_extensions=normalize_allowed_extensions(values.get(IMPORT_ALLOWED_EXTENSIONS_KEY)),
        ignore_patterns=normalize_ignore_patterns(values.get(IMPORT_IGNORE_PATTERNS_KEY)),
    )


def parse_ignore_patterns(value: str | None) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def matches_ignore_patterns(path: str | Path, patterns: str | None) -> bool:
    candidate = Path(path)
    normalized_path = candidate.as_posix()
    return any(
        fnmatch.fnmatch(candidate.name, pattern)
        or fnmatch.fnmatch(normalized_path, pattern)
        or ("*" not in pattern and "?" not in pattern and pattern in candidate.name)
        for pattern in parse_ignore_patterns(patterns)
    )


def extension_is_allowed(path: str | Path, preferences: ImportPreferences) -> bool:
    candidate = Path(path)
    return candidate.is_dir() or candidate.suffix.lower() in preferences.allowed_extensions
