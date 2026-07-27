from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any

from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.runner import head_revision

BACKUP_TABLES: list[tuple[str, str]] = [
    ("users", "User"),
    ("userPreferences", "UserPreference"),
    ("shelves", "Shelf"),
    ("monitorFolders", "MonitorFolder"),
    ("userMonitorFolderAccess", "UserMonitorFolderAccess"),
    ("works", "LibraryWork"),
    ("editions", "LibraryEdition"),
    ("volumes", "LibraryVolume"),
    ("files", "LibraryFile"),
    ("readingUnits", "LibraryReadingUnit"),
    ("metadataItems", "LibraryMetadata"),
    ("shelfWorks", "ShelfWork"),
    ("readingProgresses", "LibraryReadingProgress"),
    ("consumptionStates", "LibraryConsumptionState"),
    ("workDetailPreferences", "WorkDetailPreference"),
    ("importTasks", "ImportTask"),
    ("importAssets", "ImportAsset"),
    ("bookConversionTasks", "BookConversionTask"),
    ("importLogs", "ImportLog"),
    ("organizeJobs", "OrganizeJob"),
    ("metadataSuggestions", "MetadataSuggestion"),
    ("duplicateCandidates", "DuplicateCandidate"),
    ("metadataLookupTasks", "MetadataLookupTask"),
    ("externalMetadataCache", "ExternalMetadataCache"),
    ("bookIdentityCache", "BookIdentityCache"),
    ("readerPreferences", "ReaderPreference"),
    ("readerBookPreferences", "ReaderBookPreference"),
    ("readerProgressCursors", "ReaderProgressCursor"),
    ("readerBookmarks", "ReaderBookmark"),
    ("systemSettings", "SystemSetting"),
]

RESTORE_ORDER = [
    "ReaderBookmark",
    "UserMonitorFolderAccess",
    "UserPreference",
    "BookIdentityCache",
    "ExternalMetadataCache",
    "MetadataLookupTask",
    "DuplicateCandidate",
    "MetadataSuggestion",
    "OrganizeJob",
    "SystemSetting",
    "ReaderBookPreference",
    "ReaderProgressCursor",
    "ReaderPreference",
    "WorkDetailPreference",
    "LibraryConsumptionState",
    "ImportLog",
    "BookConversionTask",
    "ImportTask",
    "ImportAsset",
    "LibraryReadingProgress",
    "ShelfWork",
    "Shelf",
    "LibraryMetadata",
    "LibraryReadingUnit",
    "LibraryFile",
    "LibraryVolume",
    "LibraryEdition",
    "LibraryWork",
    "MonitorFolder",
]


@dataclass(frozen=True)
class BackupResult:
    id: str
    filename: str
    size_bytes: int
    created_at: str
    counts: dict[str, int]


def backup_dir(settings: Settings) -> Path:
    path = settings.resolved_storage_root / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_id(kind: str = "manual", created_at: datetime | None = None) -> str:
    date = created_at or datetime.now(timezone.utc)
    return f"{kind}-{date.strftime('%Y%m%d-%H%M%S')}-{token_hex(3)}"


def assert_backup_id(value: str) -> None:
    if not re.fullmatch(r"(manual|automatic)-\d{8}-\d{6}-[a-z0-9]+|backup-\d+", value):
        raise ValueError("INVALID_BACKUP_ID")


def backup_path(settings: Settings, backup_id_value: str) -> Path:
    assert_backup_id(backup_id_value)
    return backup_dir(settings) / f"{backup_id_value}.zip"


def table_names(db: Session) -> set[str]:
    return set(inspect(db.get_bind()).get_table_names())


def columns(db: Session, table: str) -> list[str]:
    return [column["name"] for column in inspect(db.get_bind()).get_columns(table)]


def fetch_table(db: Session, table: str) -> list[dict[str, Any]]:
    if table not in table_names(db):
        return []
    order = "`createdAt` ASC" if "createdAt" in columns(db, table) else "1"
    return [dict(row) for row in db.execute(text(f"SELECT * FROM `{table}` ORDER BY {order}")).mappings().all()]


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=json_default).encode("utf-8")


def counts_for_export(database_export: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        "users": len(database_export.get("users", [])),
        "userPreferences": len(database_export.get("userPreferences", [])),
        "monitorFolders": len(database_export.get("monitorFolders", [])),
        "userMonitorFolderAccess": len(database_export.get("userMonitorFolderAccess", [])),
        "works": len(database_export.get("works", [])),
        "editions": len(database_export.get("editions", [])),
        "volumes": len(database_export.get("volumes", [])),
        "files": len(database_export.get("files", [])),
        "readingUnits": len(database_export.get("readingUnits", [])),
        "metadataItems": len(database_export.get("metadataItems", [])),
        "shelves": len(database_export.get("shelves", [])),
        "shelfWorks": len(database_export.get("shelfWorks", [])),
        "readingProgresses": len(database_export.get("readingProgresses", [])),
        "consumptionStates": len(database_export.get("consumptionStates", [])),
        "workDetailPreferences": len(database_export.get("workDetailPreferences", [])),
        "importTasks": len(database_export.get("importTasks", [])),
        "importAssets": len(database_export.get("importAssets", [])),
        "bookConversionTasks": len(database_export.get("bookConversionTasks", [])),
        "importLogs": len(database_export.get("importLogs", [])),
        "readerPreferences": len(database_export.get("readerPreferences", [])),
        "readerBookPreferences": len(database_export.get("readerBookPreferences", [])),
        "readerProgressCursors": len(database_export.get("readerProgressCursors", [])),
        "readerBookmarks": len(database_export.get("readerBookmarks", [])),
        "systemSettings": len(database_export.get("systemSettings", [])),
        "coverIndexEntries": len(database_export.get("coverIndex", [])),
    }


def current_database_revision(db: Session) -> str:
    revision = MigrationContext.configure(db.connection()).get_current_revision()
    if revision is None:
        raise RuntimeError("database has no Alembic revision")
    return revision


def create_backup(db: Session, settings: Settings, kind: str = "manual") -> BackupResult:
    if kind != "manual":
        raise ValueError("BACKUP_KIND_UNSUPPORTED")
    created_at = datetime.now(timezone.utc)
    backup_id_value = backup_id(kind, created_at)
    database_export = {export_key: fetch_table(db, table) for export_key, table in BACKUP_TABLES}
    database_export["coverIndex"] = [
        {"workId": work.get("id"), "coverPath": work.get("coverPath"), "coverStatus": work.get("coverStatus")}
        for work in database_export.get("works", [])
    ]
    counts = counts_for_export(database_export)
    counts["libraryFiles"] = 0
    metadata = {
        "id": backup_id_value,
        "kind": kind,
        "app": "shuku-starship",
        "version": 2,
        "databaseRevision": current_database_revision(db),
        "createdAt": created_at.isoformat(),
        "format": "zip",
        "contents": ["metadata.json", "database-export.json", "settings.json"],
        "scope": ["database-v2", "system-settings", "library-metadata", "reading-metadata", "tags", "reading-progress", "monitor-folder-settings", "multi-user-authorization", "user-preferences", "reader-bookmarks", "cover-cache-index"],
        "excludes": ["reader-content-files", "cover-image-files", "library-files/"],
        "counts": counts,
    }
    settings_export = {
        "monitorFolders": database_export.get("monitorFolders", []),
        "systemSettings": database_export.get("systemSettings", []),
        "storageRoot": str(settings.resolved_storage_root),
        "backupRoot": str(backup_dir(settings)),
        "backupMode": "manual",
    }
    path = backup_path(settings, backup_id_value)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json_bytes(metadata))
        archive.writestr("database-export.json", json_bytes(database_export))
        archive.writestr("settings.json", json_bytes(settings_export))
    result = BackupResult(backup_id_value, path.name, path.stat().st_size, created_at.isoformat(), counts)
    return result


def read_backup_metadata(path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read("metadata.json").decode("utf-8"))
    except Exception:
        return None


def list_backups(settings: Settings) -> list[dict[str, Any]]:
    backups = []
    for path in backup_dir(settings).glob("*.zip"):
        metadata = read_backup_metadata(path)
        stat = path.stat()
        backups.append(
            {
                "id": metadata.get("id") if metadata else path.stem,
                "kind": metadata.get("kind") if metadata else "unknown",
                "name": path.name,
                "filename": path.name,
                "sizeBytes": stat.st_size,
                "createdAt": metadata.get("createdAt") if metadata else datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "counts": metadata.get("counts") if metadata else None,
            }
        )
    return sorted(backups, key=lambda item: str(item.get("createdAt") or ""), reverse=True)


def delete_backup_file(settings: Settings, backup_id_value: str) -> bool:
    path = backup_path(settings, backup_id_value)
    if not path.exists():
        return False
    path.unlink()
    return True


def parse_backup(path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
        database_export = json.loads(archive.read("database-export.json").decode("utf-8"))
    if metadata.get("app") != "shuku-starship" or metadata.get("version") != 2:
        raise ValueError("BACKUP_VERSION_UNSUPPORTED")
    return metadata, database_export


def insert_records(db: Session, table: str, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    if table not in table_names(db):
        return 0
    allowed = set(columns(db, table))
    inserted = 0
    for record in records:
        filtered = {key: value for key, value in record.items() if key in allowed}
        if not filtered:
            continue
        keys = ", ".join(f"`{key}`" for key in filtered)
        params = ", ".join(f":{key}" for key in filtered)
        db.execute(text(f"INSERT INTO `{table}` ({keys}) VALUES ({params})"), filtered)
        inserted += 1
    db.commit()
    return inserted


def upsert_user_records(db: Session, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    if "User" not in table_names(db):
        return 0
    allowed = set(columns(db, "User"))
    restored = 0
    for record in records:
        filtered = {key: value for key, value in record.items() if key in allowed}
        if not filtered:
            continue
        existing = None
        if filtered.get("id"):
            existing = db.execute(text("SELECT `id` FROM `User` WHERE `id` = :id"), {"id": filtered["id"]}).scalar()
        if not existing and filtered.get("email"):
            existing = db.execute(text("SELECT `id` FROM `User` WHERE `email` = :email"), {"email": filtered["email"]}).scalar()
        if existing:
            assignments = ", ".join(f"`{key}` = :{key}" for key in filtered if key != "id")
            if assignments:
                db.execute(text(f"UPDATE `User` SET {assignments} WHERE `id` = :existing_id"), {**filtered, "existing_id": existing})
            restored += 1
            continue
        keys = ", ".join(f"`{key}`" for key in filtered)
        params = ", ".join(f":{key}" for key in filtered)
        db.execute(text(f"INSERT INTO `User` ({keys}) VALUES ({params})"), filtered)
        restored += 1
    db.commit()
    return restored


def clear_table_if_present(db: Session, table: str) -> None:
    try:
        db.execute(text(f"DELETE FROM `{table}`"))
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def restore_backup(db: Session, settings: Settings, backup_id_value: str) -> dict[str, Any]:
    path = backup_path(settings, backup_id_value)
    if not path.exists():
        raise FileNotFoundError("备份不存在")
    metadata, database_export = parse_backup(path)
    supported_revision = head_revision(db.connection().engine)
    if (
        metadata.get("databaseRevision") != supported_revision
        or current_database_revision(db) != supported_revision
    ):
        raise ValueError("BACKUP_DATABASE_REVISION_UNSUPPORTED")
    for table in RESTORE_ORDER:
        clear_table_if_present(db, table)
    restored: dict[str, int] = {}
    for export_key, table in BACKUP_TABLES:
        restored[export_key] = upsert_user_records(db, database_export.get(export_key, [])) if table == "User" else insert_records(db, table, database_export.get(export_key, []))
    restored["libraryFiles"] = 0
    actual_counts = {export_key: len(fetch_table(db, table)) for export_key, table in BACKUP_TABLES}
    return {"id": backup_id_value, "restored": True, "restoredAt": datetime.now(timezone.utc).isoformat(), "counts": metadata.get("counts"), "restoredCounts": restored, "actualCounts": actual_counts}
