"""Admin-controlled service activation and an explicit public transport origin."""

from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from app.contracts.automation import AUTOMATION_SETTINGS_KEY
from app.modules.automation.application.audit import AutomationAuditPort
from app.modules.automation.application.grants import (
    AutomationIdentityPort,
    GrantUnitOfWork,
)
from app.modules.automation.domain.access import AutomationAccessError, Scope

__all__ = [
    "AUTOMATION_SETTINGS_KEY",
    "AutomationServiceSettings",
    "AutomationSettingsPort",
    "ConfigureAutomation",
    "normalize_service_settings",
]


@dataclass(frozen=True, slots=True)
class AutomationServiceSettings:
    enabled: bool = False
    enabled_scopes: frozenset[Scope] = frozenset({Scope.SYSTEM_READ})
    public_base_url: str = ""


class AutomationSettingsPort(Protocol):
    def load(self) -> AutomationServiceSettings: ...
    def save(self, settings: AutomationServiceSettings) -> None: ...


def normalize_service_settings(
    settings: AutomationServiceSettings,
) -> AutomationServiceSettings:
    if Scope.SYSTEM_READ not in settings.enabled_scopes:
        raise AutomationAccessError("SYSTEM_READ_REQUIRED")
    value = settings.public_base_url.strip().rstrip("/")
    if not value:
        if settings.enabled:
            raise AutomationAccessError("PUBLIC_URL_REQUIRED")
        return replace(settings, public_base_url="")
    try:
        url = urlsplit(value)
        _ = url.port
    except ValueError as error:
        raise AutomationAccessError("INVALID_PUBLIC_URL") from error
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or any(char.isspace() or ord(char) < 32 for char in value)
        or "\\" in value
        or "%" in value
        or any(part in {".", ".."} for part in url.path.split("/"))
    ):
        raise AutomationAccessError("INVALID_PUBLIC_URL")
    return replace(
        settings,
        public_base_url=urlunsplit(
            (url.scheme, url.netloc, url.path.rstrip("/"), "", "")
        ),
    )


class ConfigureAutomation:
    def __init__(
        self,
        store: AutomationSettingsPort,
        identities: AutomationIdentityPort,
        uow: GrantUnitOfWork,
        audit: AutomationAuditPort,
    ) -> None:
        self._store = store
        self._identities = identities
        self._uow = uow
        self._audit = audit

    def read(self, user_id: str) -> AutomationServiceSettings:
        actor = self._identities.current_actor(user_id)
        if actor is None or not actor.active:
            raise AutomationAccessError("UNAUTHORIZED")
        return self._store.load()

    def update(
        self, user_id: str, settings: AutomationServiceSettings
    ) -> AutomationServiceSettings:
        actor = self._identities.current_actor(user_id)
        if actor is None or not actor.active:
            raise AutomationAccessError("UNAUTHORIZED")
        if not actor.is_admin:
            raise AutomationAccessError("ADMIN_REQUIRED")
        normalized = normalize_service_settings(settings)
        event = self._audit.prepare(
            "settings.updated", user_id, AUTOMATION_SETTINGS_KEY
        )
        try:
            self._store.save(normalized)
            self._audit.write(event)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return normalized
