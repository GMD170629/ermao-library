"""Import composition boundary.

Only the target ContinueImport graph is assembled here.  Library writes and
uploads are kept as small composition helpers so HTTP adapters do not know
which ORM adapter owns them; task processing is exclusively delegated to
``LibraryImportTask``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import (
    ReadableResourcePipeline,
    build_readable_resource_pipeline,
    build_readable_resource_worker,
    continue_library_import,
    continue_source_import,
)
from app.modules.imports.application.library_commands import (
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryUpdate,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImportResult,
)
from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
)
from app.modules.imports.infrastructure.library_write import (
    SqlAlchemyLibraryWriteStore,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)


def persist_import_library_create(
    db: Session,
    prepared: PreparedLibraryCreate,
) -> None:
    """Persist a library row and its event in one caller-visible transaction."""

    try:
        SqlAlchemyLibraryWriteStore(db).create(prepared)
        db.commit()
    except Exception:
        db.rollback()
        raise


def persist_import_library_update(
    db: Session,
    prepared: PreparedLibraryUpdate,
) -> None:
    try:
        SqlAlchemyLibraryWriteStore(db).update(prepared)
        db.commit()
    except Exception:
        db.rollback()
        raise


def persist_import_library_delete(
    db: Session,
    prepared: PreparedLibraryDelete,
) -> bool:
    try:
        deleted = SqlAlchemyLibraryWriteStore(db).delete(prepared)
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise


def save_uploaded_files(
    command: SaveUploadedFilesCommand,
) -> tuple[SavedUploadFile, ...]:
    """Publish upload files atomically, outside any database transaction."""

    return SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(command)


__all__ = [
    "ContinueImportResult",
    "ReadableResourcePipeline",
    "ReadableResourceWorkerProcessor",
    "build_readable_resource_pipeline",
    "build_readable_resource_worker",
    "continue_library_import",
    "continue_source_import",
    "persist_import_library_create",
    "persist_import_library_delete",
    "persist_import_library_update",
    "save_uploaded_files",
]
