"""A fresh database session and authorization snapshot for every invocation."""

import logging
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.deletions import AutomationDeletions
from app.modules.automation.application.file_moves import AutomationFileMoves
from app.modules.automation.application.grants import (
    AuthorizeAutomation,
    RecordGrantUse,
)
from app.modules.automation.application.operations import AutomationOperations
from app.modules.automation.application.runtime import (
    AutomationRequest,
    CatalogInvocation,
    DeletionInvocation,
    FileInvocation,
    OperationInvocation,
    SystemInvocation,
    UploadInvocation,
    WritebackInvocation,
    WriteInvocation,
)
from app.modules.automation.application.settings import AutomationSettingsPort
from app.modules.automation.application.system import AutomationSystem
from app.modules.automation.application.uploads import AutomationUploads
from app.modules.automation.application.writebacks import AutomationWritebacks
from app.modules.automation.application.writes import AutomationWrites
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
        writes: Callable[[Session], AutomationWrites],
        files: Callable[[Session], AutomationFileMoves],
        writebacks: Callable[[Session], AutomationWritebacks],
        uploads: Callable[[Session], AutomationUploads],
        system: Callable[[Session], AutomationSystem],
        deletions: Callable[[Session], AutomationDeletions],
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._authorize = authorize
        self._catalog = catalog
        self._maintenance = maintenance
        self._usage = usage
        self._writes = writes
        self._files = files
        self._writebacks = writebacks
        self._uploads = uploads
        self._system = system
        self._deletions = deletions

    def _check_maintenance(self, db: Session) -> None:
        if self._maintenance(db):
            raise AutomationAccessError("DATABASE_MAINTENANCE")

    def deletions(
        self, access: EffectiveAccess, operation: DeletionInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._deletions(db), current)
        )

    def system(
        self, access: EffectiveAccess, operation: SystemInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._system(db), current)
        )

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
        return self._invoke_current(
            access, lambda db, current: operation(self._catalog(db), current)
        )

    def _record_usage(self, grant_id: str) -> None:
        # Usage telemetry cannot turn a committed mutation into an apparent failure.
        try:
            with self._sessions() as db:
                self._usage(db).execute(grant_id)
        except SQLAlchemyError:
            logging.getLogger(__name__).warning("automation.usage_record_failed")

    def write(
        self, access: EffectiveAccess, operation: WriteInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._writes(db), current)
        )

    def files(
        self, access: EffectiveAccess, operation: FileInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._files(db), current)
        )

    def writebacks(
        self, access: EffectiveAccess, operation: WritebackInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._writebacks(db), current)
        )

    def uploads(
        self, access: EffectiveAccess, operation: UploadInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access, lambda db, current: operation(self._uploads(db), current)
        )

    def operations(
        self, access: EffectiveAccess, operation: OperationInvocation
    ) -> dict[str, object]:
        return self._invoke_current(
            access,
            lambda db, current: operation(
                AutomationOperations(
                    self._files(db),
                    self._writebacks(db),
                    self._uploads(db),
                    self._deletions(db),
                ),
                current,
            ),
        )

    def _invoke_current(
        self,
        access: EffectiveAccess,
        operation: Callable[[Session, EffectiveAccess], dict[str, object]],
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
            result = operation(db, current)
        self._record_usage(access.grant_id)
        return result
