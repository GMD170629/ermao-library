"""Filesystem and database adapter for Backup application use cases."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.backup.application.operations import (
    BackupArchive,
    BackupDownloadDescriptor,
    BackupFormatError,
    BackupNotFoundError,
    BackupRestoreResult,
)
from app.modules.backup.infrastructure import archive


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise BackupFormatError("BACKUP_CREATED_AT_INVALID")


def _counts(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BackupFormatError("BACKUP_COUNTS_INVALID")
    result: dict[str, int] = {}
    for key, count in value.items():
        if isinstance(count, bool) or not isinstance(count, (str, int, float)):
            raise BackupFormatError("BACKUP_COUNTS_INVALID")
        result[str(key)] = int(count)
    return result


def _integer(value: object, error_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise BackupFormatError(error_code)
    return int(value)


def _archive(record: dict[str, object]) -> BackupArchive:
    return BackupArchive(
        id=str(record["id"]),
        kind=str(record.get("kind") or "unknown"),
        name=str(record["name"]),
        filename=str(record.get("filename") or record["name"]),
        size_bytes=_integer(record["sizeBytes"], "BACKUP_SIZE_INVALID"),
        created_at=_datetime(record["createdAt"]),
        counts=_counts(record.get("counts")),
    )


class FileSystemBackupArchiveStore:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def create(self) -> BackupArchive:
        result = archive.create_backup(self._db, self._settings)
        return BackupArchive(
            id=result.id,
            kind="manual",
            name=result.filename,
            filename=result.filename,
            size_bytes=result.size_bytes,
            created_at=_datetime(result.created_at),
            counts=dict(result.counts),
        )

    def list(self) -> tuple[BackupArchive, ...]:
        return tuple(
            _archive(record) for record in archive.list_backups(self._settings)
        )

    def get(self, backup_id: str) -> BackupArchive | None:
        path = archive.backup_path(self._settings, backup_id)
        if not path.exists():
            return None
        return next((item for item in self.list() if item.id == backup_id), None)

    def delete(self, backup_id: str) -> bool:
        return archive.delete_backup_file(self._settings, backup_id)

    def restore(self, backup_id: str) -> BackupRestoreResult:
        try:
            result = archive.restore_backup(self._db, self._settings, backup_id)
        except FileNotFoundError as exc:
            raise BackupNotFoundError(backup_id) from exc
        except ValueError as exc:
            if str(exc) == "INVALID_BACKUP_ID":
                raise BackupNotFoundError(backup_id) from exc
            raise
        return BackupRestoreResult(
            id=str(result["id"]),
            restored_at=_datetime(result["restoredAt"]),
            counts=_counts(result.get("counts")),
            restored_counts=_counts(result["restoredCounts"]) or {},
            actual_counts=_counts(result["actualCounts"]) or {},
        )

    def download(self, backup_id: str) -> BackupDownloadDescriptor:
        path = archive.backup_path(self._settings, backup_id)
        if not path.exists():
            raise BackupNotFoundError(backup_id)
        return BackupDownloadDescriptor(
            archive_path=str(path),
            filename=f"{backup_id}.zip",
        )
