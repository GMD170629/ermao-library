"""Compose cleanup for the existing single-consumer worker."""

from sqlalchemy.orm import Session

from app.modules.imports.application.library_cleanup import ProcessLibraryCleanup
from app.modules.imports.infrastructure.library_cleanup import (
    SqlAlchemyLibraryCleanupStore,
)


def build_library_cleanup(db: Session) -> ProcessLibraryCleanup:
    return ProcessLibraryCleanup(SqlAlchemyLibraryCleanupStore(db), db)
