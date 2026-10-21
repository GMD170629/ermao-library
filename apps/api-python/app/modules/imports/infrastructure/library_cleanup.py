"""Remove one bounded batch of books and their dependents atomically."""

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import LibraryBook
from app.models.library import Library
from app.models.organize import (
    MetadataLookupTask,
    MetadataProviderExecution,
    MetadataWritebackOperation,
    MetadataWritebackPreparation,
    OrganizeJob,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)

# Count books, not rows in each dependent table. The remaining books are the
# durable resume position; failure rolls back this entire book batch.
_BOOK_BATCH_SIZE = 3000


class SqlAlchemyLibraryCleanupStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def advance(self) -> bool:
        library_id = self._db.scalar(
            select(Library.id)
            .where(Library.deletion_requested_at.is_not(None))
            .order_by(Library.deletion_requested_at, Library.id)
            .limit(1)
        )
        if library_id is None:
            return False
        # Serialize cleanup workers before selecting the batch. No book IDs
        # are loaded into Python, and all deletes use the same ordered subset.
        claimed = self._db.execute(
            update(Library).where(
                Library.id == library_id,
                Library.deletion_requested_at.is_not(None),
            ).values(enabled=False, updated_at=Library.updated_at)
        )
        if not claimed.rowcount:
            return False
        books = (
            select(LibraryBook.id)
            .where(LibraryBook.library_id == library_id)
            .order_by(LibraryBook.id)
            .limit(_BOOK_BATCH_SIZE)
        )
        for model in (MetadataWritebackPreparation, MetadataWritebackOperation):
            self._db.execute(
                delete(model).where(model.book_id.in_(books))
                .execution_options(synchronize_session=False)
            )
        for parent, parent_key in (
            (MetadataLookupTask, MetadataProviderExecution.lookup_task_id),
            (OrganizeJob, MetadataProviderExecution.job_id),
        ):
            self._db.execute(
                delete(MetadataProviderExecution).where(parent_key.in_(
                    select(parent.id).where(parent.book_id.in_(books)),
                )).execution_options(synchronize_session=False)
            )
        # These rows would otherwise be rewritten with SET NULL while the
        # selected books/resources/import tasks cascade away.
        for model in (MetadataLookupTask, OrganizeJob, LibraryImportTask):
            self._db.execute(
                delete(model).where(model.book_id.in_(books))
                .execution_options(synchronize_session=False)
            )
        self._db.execute(
            delete(LibraryBook).where(LibraryBook.id.in_(books))
            .execution_options(synchronize_session=False)
        )
        if self._db.scalar(select(LibraryBook.id).where(
            LibraryBook.library_id == library_id,
        ).limit(1)) is None:
            # Source nodes and library-wide scan tasks belong to the library,
            # not a single book. Finish them with the final book batch.
            self._db.execute(delete(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id,
            ).execution_options(synchronize_session=False))
            self._db.execute(delete(Library).where(
                Library.id == library_id, Library.deletion_requested_at.is_not(None),
            ))
        return True
