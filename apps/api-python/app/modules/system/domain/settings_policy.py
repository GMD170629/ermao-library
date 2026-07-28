"""System settings visibility and mutation policy."""

from __future__ import annotations

import json
from typing import Any


SENSITIVE_SYSTEM_SETTING_KEYS = frozenset(
    {
        "email.smtp.password",
        "metadata.bangumi.accessToken",
        "metadata.ai.apiKey",
    }
)

RETIRED_SYSTEM_SETTING_KEYS = frozenset(
    {
        "systemName",
        "metadata.douban.mode",
        "metadata.douban.baseUrl",
        "metadata.douban.apiKey",
        "download.qbittorrent.url",
        "download.qbittorrent.username",
        "download.qbittorrent.password",
        "download.qbittorrent.category",
        "download.qbittorrent.savePath",
    }
)

DETAIL_TAB_KEYS = ("EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE")


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def normalize_detail_tab_order(value: Any) -> list[str]:
    parsed = _parse_json(value, value)
    if not isinstance(parsed, list):
        parsed = []
    result: list[str] = []
    for raw in parsed:
        key = str(raw or "").strip().upper()
        if key in DETAIL_TAB_KEYS and key not in result:
            result.append(key)
    result.extend(key for key in DETAIL_TAB_KEYS if key not in result)
    return result


def public_system_settings(values: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {f"{key}Configured": False for key in SENSITIVE_SYSTEM_SETTING_KEYS}
    for key, value in values.items():
        if key in RETIRED_SYSTEM_SETTING_KEYS:
            continue
        if key in SENSITIVE_SYSTEM_SETTING_KEYS:
            public[f"{key}Configured"] = bool(str(value).strip()) if value is not None else False
        else:
            public[key] = value
    return public


def retired_setting_keys_in(values: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in values if str(key) in RETIRED_SYSTEM_SETTING_KEYS)
