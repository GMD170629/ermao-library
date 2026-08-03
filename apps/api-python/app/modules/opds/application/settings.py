"""OPDS availability policy and public settings projection."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

OPDS_ENABLED_SETTING_KEY = "opds.enabled"
OPDS_PUBLIC_BASE_URL_SETTING_KEY = "opds.publicBaseUrl"


@dataclass(frozen=True, slots=True)
class OpdsSettingsSnapshot:
    enabled: bool
    configured: bool
    public_base_url: str | None
    catalog_url: str | None


class OpdsPublicBaseUrlRequired(ValueError):
    """Raised when OPDS is enabled without a trusted public base URL."""


class OpdsPublicBaseUrlInvalid(ValueError):
    """Raised when the configured public URL cannot be published safely."""


def normalize_opds_public_base_url(public_base_url: str) -> str:
    normalized = public_base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise OpdsPublicBaseUrlInvalid
    return normalized


def resolve_opds_settings(
    stored_enabled: object,
    *,
    stored_public_base_url: object,
) -> OpdsSettingsSnapshot:
    try:
        normalized_base_url = (
            normalize_opds_public_base_url(stored_public_base_url)
            if isinstance(stored_public_base_url, str)
            and stored_public_base_url.strip()
            else None
        )
    except OpdsPublicBaseUrlInvalid:
        normalized_base_url = None
    configured = normalized_base_url is not None
    requested_enabled = stored_enabled if isinstance(stored_enabled, bool) else False
    enabled = requested_enabled and configured
    return OpdsSettingsSnapshot(
        enabled=enabled,
        configured=configured,
        public_base_url=normalized_base_url,
        catalog_url=(
            f"{normalized_base_url}/opds/v1.2/catalog"
            if enabled and normalized_base_url is not None
            else None
        ),
    )


def validate_opds_activation(enabled: bool, public_base_url: str | None) -> str | None:
    if enabled and not (public_base_url or "").strip():
        raise OpdsPublicBaseUrlRequired
    if not (public_base_url or "").strip():
        return None
    return normalize_opds_public_base_url(public_base_url or "")
