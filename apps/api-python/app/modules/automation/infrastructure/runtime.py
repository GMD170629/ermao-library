"""A fresh database session and authorization snapshot for every invocation."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.core.exception_diagnostics import (
    DiagnosticSnapshot,
    deferred_exception_persistence,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
    record_exception,
)
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

    @contextmanager
    def _session(self, *, stage: str = "automation_invocation") -> Iterator[Session]:
        """Capture the first failure before releasing a business transaction."""
        logger = logging.getLogger(__name__)
        pending: list[DiagnosticSnapshot] = []
        try:
            with deferred_exception_persistence() as pending:
                db = self._sessions()
                original: DiagnosticSnapshot | None = None
                try:
                    yield db
                except Exception as error:
                    original = prepare_exception_diagnostic(
                        logger,
                        "automation.invocation_failed",
                        error,
                        context={"stage": stage},
                        source="automation",
                    )
                    raise
                finally:
                    try:
                        db.close()
                    except Exception as error:
                        prepare_exception_diagnostic(
                            logger,
                            "automation.session_close_failed",
                            error,
                            context={
                                "stage": "session_close",
                                "parent_diagnostic_id": original.diagnostic_id
                                if original
                                else None,
                            },
                            source="automation",
                        )
                        if original is None:
                            raise
        finally:
            for snapshot in pending:
                persist_exception_diagnostic(logger, snapshot, self._sessions)

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
        with self._session(stage="mcp_authentication") as db:
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
            with self._session(stage="record_grant_usage") as db:
                self._usage(db).execute(grant_id)
        except Exception as error:  # noqa: BLE001 - usage telemetry is non-fatal but diagnosed
            record_exception(
                logging.getLogger(__name__),
                "automation.usage_record_failed",
                error,
                level="warning",
                context={"stage": "record_grant_usage", "resource_id": grant_id},
                source="automation",
                session_factory=self._sessions,
            )

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
        with self._session() as db:
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
