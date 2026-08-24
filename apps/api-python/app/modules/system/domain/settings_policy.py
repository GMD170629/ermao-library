"""System settings visibility and mutation policy."""

from __future__ import annotations

from typing import Any

SENSITIVE_SYSTEM_SETTING_KEYS = frozenset(
    {
        "email.smtp.password",
    }
)

RETIRED_SYSTEM_SETTING_KEYS = frozenset(
    {
        "systemName",
        "metadata.external.enabled",
        "metadata.douban.enabled",
        "metadata.douban.mode",
        "metadata.douban.baseUrl",
        "metadata.douban.apiKey",
        "metadata.douban.userAgent",
        "metadata.bangumi.enabled",
        "metadata.bangumi.baseUrl",
        "metadata.bangumi.accessToken",
        "metadata.bangumi.userAgent",
        "metadata.ai.enabled",
        "metadata.ai.baseUrl",
        "metadata.ai.apiKey",
        "metadata.ai.model",
        "download.qbittorrent.url",
        "download.qbittorrent.username",
        "download.qbittorrent.password",
        "download.qbittorrent.category",
        "download.qbittorrent.savePath",
    }
)

def public_system_settings(values: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {
        f"{key}Configured": False for key in SENSITIVE_SYSTEM_SETTING_KEYS
    }
    for key, value in values.items():
        if key in RETIRED_SYSTEM_SETTING_KEYS:
            continue
        if key in SENSITIVE_SYSTEM_SETTING_KEYS:
            public[f"{key}Configured"] = (
                bool(str(value).strip()) if value is not None else False
            )
        else:
            public[key] = value
    return public


def retired_setting_keys_in(values: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in values if str(key) in RETIRED_SYSTEM_SETTING_KEYS)
