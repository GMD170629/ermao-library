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
    CreateLibrary,
    DeleteLibrary,
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryUpdate,
    UpdateLibrary,
)
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImportResult,
)
from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
)
from app.modules.imports.infrastructure.library_queries import (
    get_import_task,
    get_library,
    get_library_by_root_path,
    library_has_topology,
    list_enabled_library_rows,
    list_import_tasks_page,
    list_libraries,
    list_library_access_user_ids,
    source_node_library_id,
)
from app.modules.imports.infrastructure.library_write import (
    SqlAlchemyLibraryWriteStore,
)
from app.modules.imports.infrastructure.readable_resource.worker import (
    ReadableResourceWorkerProcessor,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)


def persist_import_library_create(
    db: Session,
    prepared: PreparedLibraryCreate,
) -> None:
    """Persist a library row and its event in one caller-visible transaction."""

    CreateLibrary(SqlAlchemyLibraryWriteStore(db), db).execute(prepared)


def persist_import_library_update(
    db: Session,
    prepared: PreparedLibraryUpdate,
) -> None:
    UpdateLibrary(SqlAlchemyLibraryWriteStore(db), db).execute(prepared)


def persist_import_library_delete(
    db: Session,
    prepared: PreparedLibraryDelete,
) -> bool:
    return DeleteLibrary(SqlAlchemyLibraryWriteStore(db), db).execute(prepared)


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
    "get_import_task",
    "get_library",
    "get_library_by_root_path",
    "library_has_topology",
    "list_enabled_library_rows",
    "list_import_tasks_page",
    "list_libraries",
    "list_library_access_user_ids",
    "persist_import_library_create",
    "persist_import_library_delete",
    "persist_import_library_update",
    "save_uploaded_files",
    "source_node_library_id",
]
