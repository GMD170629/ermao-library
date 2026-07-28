"""Recoverable filesystem coordination for deleting an import task."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from app.modules.imports.application.ports import ImportUnitOfWork

ResultT = TypeVar("ResultT")


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


def execute_import_deletion(
    unit_of_work: ImportUnitOfWork,
    files: ImportDeletionFiles,
    owner_id: str,
    paths: Sequence[str],
    database_operation: Callable[[], ResultT],
) -> tuple[ResultT, FileCleanupResult]:
    """Commit database deletion only while the corresponding files are recoverable."""

    token = files.quarantine(owner_id, paths)
    try:
        result = database_operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        files.restore(token)
        raise
    return result, files.finalize(token)
