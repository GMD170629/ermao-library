"""Recheck current authority after claiming the durable mutation transaction."""

from dataclasses import dataclass

from app.modules.automation.application.grants import AuthorizeAutomation
from app.modules.automation.application.settings import AutomationSettingsPort
from app.modules.automation.domain.access import EffectiveAccess, Scope


@dataclass(frozen=True)
class RecheckMutationAccess:
    authorizer: AuthorizeAutomation
    settings: AutomationSettingsPort

    def require(self, access: EffectiveAccess, *scopes: Scope) -> EffectiveAccess:
        settings = self.settings.load()
        current = self.authorizer.operation(
            grant_id=access.grant_id,
            user_id=access.user_id,
            service_enabled=settings.enabled,
            enabled_scopes=settings.enabled_scopes,
        )
        current.require(*scopes)
        return current
