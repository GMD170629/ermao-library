"""Named Backup application use cases and stable archive contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BackupNotFoundError(LookupError):
    """The requested backup archive does not exist."""


class BackupFormatError(ValueError):
    """The archive cannot be mapped to the supported backup contract."""


@dataclass(frozen=True, slots=True)
class BackupArchive:
    id: str
    kind: str
    name: str
    filename: str
    size_bytes: int
    created_at: datetime
    counts: dict[str, int] | None


@dataclass(frozen=True, slots=True)
class BackupRestoreResult:
    id: str
    restored_at: datetime
    counts: dict[str, int] | None
    restored_counts: dict[str, int]
    actual_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class BackupDownloadDescriptor:
    archive_path: str
    filename: str


class BackupArchiveStore(Protocol):
    def create(self) -> BackupArchive: ...

    def list(self) -> tuple[BackupArchive, ...]: ...

    def get(self, backup_id: str) -> BackupArchive | None: ...

    def delete(self, backup_id: str) -> bool: ...

    def restore(self, backup_id: str) -> BackupRestoreResult: ...

    def download(self, backup_id: str) -> BackupDownloadDescriptor: ...


class CreateBackup:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self) -> BackupArchive:
        return self._archive_store.create()


class ListBackups:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self) -> tuple[BackupArchive, ...]:
        return self._archive_store.list()


class GetBackup:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self, backup_id: str) -> BackupArchive:
        backup = self._archive_store.get(backup_id)
        if backup is None:
            raise BackupNotFoundError(backup_id)
        return backup


class DeleteBackup:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self, backup_id: str) -> bool:
        return self._archive_store.delete(backup_id)


class RestoreBackup:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self, backup_id: str) -> BackupRestoreResult:
        return self._archive_store.restore(backup_id)


class GetBackupDownload:
    def __init__(self, archive_store: BackupArchiveStore) -> None:
        self._archive_store = archive_store

    def execute(self, backup_id: str) -> BackupDownloadDescriptor:
        return self._archive_store.download(backup_id)
