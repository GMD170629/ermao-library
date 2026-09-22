"""Automation contracts for adapters, HTTP and durable operation owners."""

from app.modules.automation.application.audit import (
    AutomationAuditAction,
    AutomationAuditPort,
)
from app.modules.automation.application.grants import (
    AuthorizeAutomation,
    AutomationGrant,
    AutomationIdentityPort,
    CreatedGrant,
    ManageGrants,
)
from app.modules.automation.application.settings import (
    AUTOMATION_SETTINGS_KEY,
    AutomationServiceSettings,
    AutomationSettingsPort,
    normalize_service_settings,
)
from app.modules.automation.application.system import ConfigurationGroup
from app.modules.automation.domain.access import (
    AutomationAccessError,
    AutomationActor,
    EffectiveAccess,
    GrantPermissions,
    Scope,
    WritebackTarget,
)

__all__ = [
    "AUTOMATION_SETTINGS_KEY",
    "AuthorizeAutomation",
    "AutomationAccessError",
    "AutomationActor",
    "AutomationAuditAction",
    "AutomationAuditPort",
    "AutomationGrant",
    "AutomationIdentityPort",
    "AutomationServiceSettings",
    "AutomationSettingsPort",
    "ConfigurationGroup",
    "CreatedGrant",
    "EffectiveAccess",
    "GrantPermissions",
    "ManageGrants",
    "Scope",
    "WritebackTarget",
    "normalize_service_settings",
]
