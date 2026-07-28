"""SQLAlchemy-backed ``ImportPipeline`` adapter bound to one Session."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
)
from app.modules.imports.application.managed_book import import_managed_book
from app.modules.imports.infrastructure.library_import_store import (
    SqlAlchemyLibraryImportStore,
)
from app.modules.imports.infrastructure.query_adapter import (
    SqlAlchemyImportLibraryQueries,
)
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork


class SessionImportPipeline:
    """Adapts ``import_managed_book`` to the ``ImportPipeline`` port for one Session.

    The Session is used only as the explicit checkpoint UoW. Concrete
    collaborators are exposed to application code through named ports.
    """

    def __init__(
        self,
        db: Session,
        settings: Settings,
        unit_of_work: SqlAlchemyImportUnitOfWork | None = None,
    ) -> None:
        self._db = db
        self._unit_of_work = unit_of_work or SqlAlchemyImportUnitOfWork(db)
        self._store = SqlAlchemyLibraryImportStore(db)
        self._queries = SqlAlchemyImportLibraryQueries(db)
        self._services = SessionImportOrchestrationServices(db, settings)

    def import_managed_book(
        self, settings: ImportRuntimeConfig, options: ImportOptions
    ) -> ImportResult:
        return import_managed_book(
            self._store,
            self._queries,
            self._unit_of_work,
            self._services,
            settings,
            options,
        )

    def finalize_publications(self) -> None:
        self._services.finalize_publications()

    def rollback_publications(self) -> None:
        self._services.rollback_publications()
