"""Recheck current authority after claiming the durable mutation transaction."""

from dataclasses import dataclass

from app.modules.automation.application.grants import AuthorizeAutomation
from app.modules.automation.application.settings import AutomationSettingsPort
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.library.public import FileMoveError, MoveActor


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


@dataclass(frozen=True)
class RecheckMoveAccess:
    authorizer: AuthorizeAutomation
    settings: AutomationSettingsPort

    def __call__(self, actor: MoveActor) -> MoveActor:
        settings = self.settings.load()
        try:
            current = self.authorizer.operation(
                grant_id=actor.grant_id,
                user_id=actor.user_id,
                service_enabled=settings.enabled,
                enabled_scopes=settings.enabled_scopes,
            )
            current.require(Scope.FILES_MOVE)
        except AutomationAccessError as error:
            raise FileMoveError("AUTHORIZATION_REVOKED") from error
        return MoveActor(
            current.user_id,
            current.grant_id,
            current.permissions.library_ids,
            current.permissions.allow_cross_library,
        )
