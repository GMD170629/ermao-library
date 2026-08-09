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
from app.modules.imports.application.transactions import (
    BoundedLibraryImportStore,
    ImportCompletion,
    ImportTransactionController,
    PreparedImport,
    persist_import_completion,
)
from app.modules.imports.infrastructure.library_import_store import (
    SqlAlchemyLibraryImportStore,
)
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.modules.imports.infrastructure.query_adapter import (
    SqlAlchemyImportLibraryQueries,
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
        self._base_store = SqlAlchemyLibraryImportStore(db)
        self._transactions = ImportTransactionController(self._unit_of_work)
        self._completion = ImportCompletion()
        self._store = BoundedLibraryImportStore(
            self._base_store,
            self._transactions,
            self._completion,
        )
        self._queries = SqlAlchemyImportLibraryQueries(db)
        self._services = SessionImportOrchestrationServices(
            db, settings, self._unit_of_work
        )
        self._prepared_import: PreparedImport | None = None

    def import_managed_book(
        self, settings: ImportRuntimeConfig, options: ImportOptions
    ) -> ImportResult:
        if options.import_task_id is not None:
            self._store.set_import_scope(
                options.import_task_id,
                options.original_source_file_path or options.source_file_path,
            )
        result = import_managed_book(
            self._store,
            self._queries,
            self._transactions,
            self._services,
            settings,
            options,
        )
        self._transactions.begin_completion()
        self._prepared_import = self._completion.prepare(result)
        return result

    def complete_import(self) -> None:
        if self._prepared_import is None:
            raise RuntimeError("import completion requested before preparation")
        persist_import_completion(self._base_store, self._prepared_import)
