"""Composition root for Backup application use cases."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.backup.application.operations import (
    CreateBackup,
    DeleteBackup,
    GetBackup,
    GetBackupDownload,
    ListBackups,
    RestoreBackup,
)
from app.modules.backup.infrastructure.archive_store import FileSystemBackupArchiveStore


@dataclass(frozen=True, slots=True)
class BackupUseCases:
    create: CreateBackup
    list: ListBackups
    get: GetBackup
    delete: DeleteBackup
    restore: RestoreBackup
    download: GetBackupDownload


def build_backup_use_cases(db: Session, settings: Settings) -> BackupUseCases:
    archive_store = FileSystemBackupArchiveStore(db, settings)
    return BackupUseCases(
        create=CreateBackup(archive_store),
        list=ListBackups(archive_store),
        get=GetBackup(archive_store),
        delete=DeleteBackup(archive_store),
        restore=RestoreBackup(archive_store),
        download=GetBackupDownload(archive_store),
    )
