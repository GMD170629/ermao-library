"""Recoverable command for deleting library works and their files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedFileQuarantineEntry:
    original_path: str
    quarantine_path: str
    quarantine_root: str
    source_file: bool


@dataclass(frozen=True, slots=True)
class PreparedLibraryWorkDeletion:
    work_ids: tuple[str, ...]
    files: tuple[PreparedFileQuarantineEntry, ...]
    events: tuple[PreparedSystemEvent, ...]


@dataclass(frozen=True, slots=True)
class IsolatedLibraryFiles:
    entries: tuple[PreparedFileQuarantineEntry, ...]
    missing_source_paths: tuple[str, ...]
    failures: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class LibraryWorkDeletionResult:
    deleted: int
    isolated_files: int
    deleted_source_files: int
    missing_source_paths: tuple[str, ...]
    failed_file_deletes: tuple[dict[str, str], ...]


class LibraryWorkDeletionStore(Protocol):
    def delete_records(self, work_ids: tuple[str, ...]) -> int: ...


class LibraryFileQuarantine(Protocol):
    def isolate(
        self, entries: tuple[PreparedFileQuarantineEntry, ...]
    ) -> IsolatedLibraryFiles: ...

    def restore(self, isolated: IsolatedLibraryFiles) -> None: ...

    def finalize(
        self, isolated: IsolatedLibraryFiles
    ) -> tuple[dict[str, str], ...]: ...


class LibraryDeletionEventStore(Protocol):
    def write(self, events: tuple[PreparedSystemEvent, ...]) -> None: ...


class LibraryDeletionUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DeleteLibraryWorks:
    def __init__(
        self,
        store: LibraryWorkDeletionStore,
        files: LibraryFileQuarantine,
        events: LibraryDeletionEventStore,
        unit_of_work: LibraryDeletionUnitOfWork,
    ) -> None:
        self._store = store
        self._files = files
        self._events = events
        self._unit_of_work = unit_of_work

    def execute(
        self, prepared: PreparedLibraryWorkDeletion
    ) -> LibraryWorkDeletionResult:
        isolated = self._files.isolate(prepared.files)
        try:
            deleted = self._store.delete_records(prepared.work_ids)
            if deleted:
                self._events.write(prepared.events)
                self._unit_of_work.commit()
            else:
                self._unit_of_work.rollback()
                self._files.restore(isolated)
        except Exception:
            self._unit_of_work.rollback()
            self._files.restore(isolated)
            raise

        finalize_failures = self._files.finalize(isolated) if deleted else ()
        source_count = sum(entry.source_file for entry in isolated.entries)
        return LibraryWorkDeletionResult(
            deleted=deleted,
            isolated_files=len(isolated.entries),
            deleted_source_files=source_count,
            missing_source_paths=isolated.missing_source_paths,
            failed_file_deletes=(*isolated.failures, *finalize_failures),
        )
