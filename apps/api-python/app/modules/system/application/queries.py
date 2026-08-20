"""Named system HTTP use cases and projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.i18n import SUPPORTED_LOCALES, configured_locale, normalize_locale
from app.core.time import to_timestamp_ms
from app.modules.system.application.projections import serialize_system_event
from app.modules.system.domain.settings_policy import (
    SENSITIVE_SYSTEM_SETTING_KEYS,
    normalize_detail_tab_order,
    public_system_settings,
    retired_setting_keys_in,
)


@dataclass(frozen=True)
class SettingsUpdateError:
    message: str
    status_code: int
    code: str | None = None
    params: dict[str, object] | None = None
    details: object | None = None


_STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def frontend_resource_status(
    current_version: str | None, latest_version: str
) -> dict[str, str | bool]:
    normalized_current = (current_version or "").strip()
    return {
        "latestVersion": latest_version,
        "updateRequired": bool(normalized_current)
        and (
            _STABLE_VERSION_PATTERN.fullmatch(normalized_current) is None
            or normalized_current != latest_version
        ),
    }


def app_config_payload(
    db: Any, *, current_frontend_resource_version: str | None, latest_version: str
) -> dict[str, Any]:
    return {
        "language": configured_locale(db),
        "supportedLocales": list(SUPPORTED_LOCALES),
        "frontendResources": frontend_resource_status(
            current_frontend_resource_version, latest_version
        ),
    }


def system_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    return {"settings": public_system_settings(values)}


def prepare_system_settings_update(
    values: dict[str, Any],
    requested_clear_keys: list[Any],
    *,
    normalize_import_setting_value: Any,
    import_preference_keys: frozenset[str] | set[str],
) -> tuple[dict[str, Any], set[str]] | SettingsUpdateError:
    if "language" in values:
        language = normalize_locale(values.get("language"), fallback=None)
        if language is None:
            return SettingsUpdateError(
                message="不支持的界面语言",
                status_code=400,
                code="INVALID_LOCALE",
                params={"supportedLocales": list(SUPPORTED_LOCALES)},
            )
        values = {**values, "language": language}
    unsupported_keys = retired_setting_keys_in(values)
    if unsupported_keys:
        return SettingsUpdateError(
            message="包含不支持修改的设置项",
            status_code=400,
            details={"keys": unsupported_keys},
        )
    clear_keys = {
        str(key)
        for key in requested_clear_keys
        if str(key) in SENSITIVE_SYSTEM_SETTING_KEYS
    }
    saved: dict[str, Any] = {}
    for raw_key, value in values.items():
        key = str(raw_key)
        if key in clear_keys:
            continue
        if key in SENSITIVE_SYSTEM_SETTING_KEYS and (
            value is None or not str(value).strip()
        ):
            continue
        if key == "workDetail.tabOrder":
            value = normalize_detail_tab_order(value)
        if key in import_preference_keys:
            value = normalize_import_setting_value(key, value)
        saved[key] = value
    return saved, clear_keys


def management_events_empty_page(page: int, page_size: int) -> dict[str, Any]:
    return {
        "events": [],
        "page": page,
        "pageSize": page_size,
        "total": 0,
        "totalPages": 1,
        "storage": {"sizeBytes": 0, "maxBytes": 5 * 1024 * 1024},
        "facets": {"sources": [], "levels": []},
    }


def management_events_payload(
    *,
    events: list[dict[str, Any]],
    total: int,
    page: int,
    page_size: int,
    storage: dict[str, Any],
    sources: list[dict[str, Any]],
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "events": [serialize_system_event(event) for event in events],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": max(1, (total + page_size - 1) // page_size),
        "storage": storage,
        "facets": {"sources": sources, "levels": levels},
    }


def parse_event_date_bounds(
    date_from: str | None,
    date_to: str | None,
) -> tuple[int | None, int | None]:
    date_from_ms = (
        to_timestamp_ms(date_from if "T" in date_from else f"{date_from}T00:00:00")
        if date_from
        else None
    )
    date_to_ms = (
        to_timestamp_ms(date_to if "T" in date_to else f"{date_to}T00:00:00")
        if date_to
        else None
    )
    return date_from_ms, date_to_ms


def dashboard_system_status_payload(
    *,
    health: dict[str, Any],
    enabled_libraries: list[dict[str, Any]],
    current_import_task: Any,
    latest_import_task: Any,
    failed_count: int,
) -> dict[str, Any]:
    checks = {item["name"]: item for item in health["checks"]}
    return {
        "database": checks.get("database", {"status": "unknown", "message": "待检测"}),
        "worker": (
            {"status": "ok", "message": "正在监听书库"}
            if enabled_libraries
            else {"status": "unknown", "message": "未启用书库"}
        ),
        "enabledLibraries": enabled_libraries,
        "currentImportTask": current_import_task,
        "latestImportTask": latest_import_task,
        "errorFileCount": failed_count,
        "libraryRootsReadable": checks.get(
            "libraryRootsReadable",
            {"status": "unknown", "message": "待检测"},
        ),
        "storageWritable": checks.get(
            "storageWritable",
            {"status": "unknown", "message": "待检测"},
        ),
    }


def backup_created_payload(backup: Any) -> dict[str, Any]:
    return {
        "backup": {
            "id": backup.id,
            "name": backup.filename,
            "filename": backup.filename,
            "sizeBytes": backup.size_bytes,
            "createdAt": backup.created_at,
            "counts": backup.counts,
        }
    }


def backup_detail_payload(
    backup_id: str,
    path: Path,
    archives: list[dict[str, Any]],
) -> dict[str, Any]:
    backup = next((item for item in archives if item["id"] == backup_id), None)
    if backup is not None:
        return {"backup": backup}
    return {
        "backup": {
            "id": backup_id,
            "name": path.name,
            "sizeBytes": path.stat().st_size,
            "createdAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        }
    }
