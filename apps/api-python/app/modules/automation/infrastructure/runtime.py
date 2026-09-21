"""A fresh database session and authorization snapshot for every invocation."""

import logging
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.grants import (
    AuthorizeAutomation,
    RecordGrantUse,
)
from app.modules.automation.application.runtime import (
    AutomationRequest,
    CatalogInvocation,
)
from app.modules.automation.application.settings import AutomationSettingsPort
from app.modules.automation.domain.access import AutomationAccessError, EffectiveAccess


class DatabaseAutomationRuntime:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Callable[[Session], AutomationSettingsPort],
        authorize: Callable[[Session], AuthorizeAutomation],
        catalog: Callable[[Session], AutomationCatalog],
        maintenance: Callable[[Session], bool],
        usage: Callable[[Session], RecordGrantUse],
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._authorize = authorize
        self._catalog = catalog
        self._maintenance = maintenance
        self._usage = usage

    def _check_maintenance(self, db: Session) -> None:
        if self._maintenance(db):
            raise AutomationAccessError("DATABASE_MAINTENANCE")

    def authenticate(self, authorization: str | None) -> AutomationRequest:
        with self._sessions() as db:
            self._check_maintenance(db)
            settings = self._settings(db).load()
            access = self._authorize(db).bearer(
                authorization,
                service_enabled=settings.enabled,
                enabled_scopes=settings.enabled_scopes,
            )
            return AutomationRequest(access, settings)

    def invoke(
        self, access: EffectiveAccess, operation: CatalogInvocation
    ) -> dict[str, object]:
        with self._sessions() as db:
            self._check_maintenance(db)
            settings = self._settings(db).load()
            current = self._authorize(db).operation(
                grant_id=access.grant_id,
                user_id=access.user_id,
                service_enabled=settings.enabled,
                enabled_scopes=settings.enabled_scopes,
            )
            result = operation(self._catalog(db), current)
        # Usage telemetry must not turn an already completed business mutation
        # into an apparent failure and trigger a client retry.
        try:
            with self._sessions() as db:
                self._usage(db).execute(access.grant_id)
        except SQLAlchemyError:
            logging.getLogger(__name__).warning("automation.usage_record_failed")
        return result
