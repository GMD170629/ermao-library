"""Recoverable filesystem coordination for deleting an import task."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.contracts.import_deletion import PreparedLibraryVolumeDeletion
from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True)
class QuarantinedFile:
    original_path: str
    quarantine_path: str


@dataclass(frozen=True)
class ImportDeletionToken:
    operation_id: str
    owner_id: str
    manifest_path: str
    files: tuple[QuarantinedFile, ...]
    missing_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileCleanupFailure:
    path: str
    message: str


@dataclass(frozen=True)
class FileCleanupResult:
    deleted_files: int
    missing_paths: tuple[str, ...]
    failures: tuple[FileCleanupFailure, ...] = ()


class ImportFileQuarantineError(RuntimeError):
    def __init__(self, failures: tuple[FileCleanupFailure, ...]) -> None:
        super().__init__("unable to quarantine import files")
        self.failures = failures


class ImportDeletionFiles(Protocol):
    def quarantine(
        self, owner_id: str, paths: Sequence[str]
    ) -> ImportDeletionToken: ...

    def restore(self, token: ImportDeletionToken) -> None: ...

    def finalize(self, token: ImportDeletionToken) -> FileCleanupResult: ...


@dataclass(frozen=True, slots=True)
class PreparedImportDeletion:
    task_id: str
    quarantine_paths: tuple[str, ...]
    library_deletion: PreparedLibraryVolumeDeletion | None
    events: tuple[PreparedSystemEvent, ...]


@dataclass(frozen=True, slots=True)
class ImportDeletionDatabaseResult:
    deleted: bool
    deleted_library_record: bool
    deleted_work_record: bool
    deleted_library_database_records: int
    library_work_id: str | None


class PreparedImportDeletionStore(Protocol):
    """SQL-only store for an already detached import deletion decision."""

    def write(self, prepared: PreparedImportDeletion) -> ImportDeletionDatabaseResult: ...


def execute_import_deletion(
    unit_of_work: ImportUnitOfWork,
    files: ImportDeletionFiles,
    store: PreparedImportDeletionStore,
    prepared: PreparedImportDeletion,
) -> tuple[ImportDeletionDatabaseResult, FileCleanupResult]:
    """Commit database deletion only while the corresponding files are recoverable."""

    # Route/query projections may have opened a read transaction. Release it
    # before path validation, manifest publication, and file quarantine.
    unit_of_work.release()
    token = files.quarantine(prepared.task_id, prepared.quarantine_paths)
    try:
        result = store.write(prepared)
        if result.deleted:
            unit_of_work.commit()
        else:
            unit_of_work.rollback()
            files.restore(token)
    except Exception:
        unit_of_work.rollback()
        files.restore(token)
        raise
    return result, files.finalize(token)
