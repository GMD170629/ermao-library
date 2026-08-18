from __future__ import annotations

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import Any

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.maintenance import (
    DATABASE_MAINTENANCE_RESTORE_VALUE,
    DATABASE_MAINTENANCE_SETTING_KEY,
    database_restore_barrier,
    database_restore_connection,
)
from app.db.runner import head_revision
from app.db.sqlite import create_sqlite_engine
from app.modules.backup.application.restore import (
    ApplyValidatedBackupRestore,
    PreparedRestorePlan,
)
from app.modules.backup.infrastructure.persistence import (
    SqlAlchemyBackupRestoreWriter,
    fetch_table,
    prepare_maintenance_state_plan,
    prepare_restore_plan,
    prepare_table_records,
    validate_restore_relationships,
)

BACKUP_TABLES: list[tuple[str, str]] = [
    ("users", "User"),
    ("userPreferences", "UserPreference"),
    ("shelves", "Shelf"),
    ("libraries", "Library"),
    ("userLibraryAccess", "UserLibraryAccess"),
    ("works", "LibraryWork"),
    ("mediaVersions", "LibraryMediaVersion"),
    ("volumes", "LibraryVolume"),
    ("files", "LibraryFile"),
    ("readingUnits", "LibraryReadingUnit"),
    ("metadataItems", "LibraryMetadata"),
    ("facets", "LibraryFacet"),
    ("workFacets", "LibraryWorkFacet"),
    ("volumeFacets", "LibraryVolumeFacet"),
    ("shelfWorks", "ShelfWork"),
    ("readingProgresses", "LibraryReadingProgress"),
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
    ("mediaVersionMigrationEvents", "MediaVersionMigrationEvent"),
    ("sources", "Source"),
    ("metadataProviderPipelines", "MetadataProviderPipeline"),
    ("systemSettings", "SystemSetting"),
]

RESTORE_ORDER = [
    "MetadataProviderPipeline",
    "Source",
    "ReaderBookmark",
    "MediaVersionMigrationEvent",
    "UserLibraryAccess",
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
    "LibraryVolumeFacet",
    "LibraryWorkFacet",
    "LibraryFacet",
    "LibraryVolume",
    "LibraryMediaVersion",
    "LibraryWork",
    "Library",
]


@dataclass(frozen=True)
class BackupResult:
    id: str
    filename: str
    size_bytes: int
    created_at: str
    counts: dict[str, int]


class BackupFormatError(ValueError):
    """The archive JSON shape cannot be mapped to the backup contract."""


def backup_dir(settings: Settings) -> Path:
    path = settings.resolved_storage_root / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_id(kind: str = "manual", created_at: datetime | None = None) -> str:
    date = created_at or datetime.now(UTC)
    return f"{kind}-{date.strftime('%Y%m%d-%H%M%S')}-{token_hex(3)}"


def assert_backup_id(value: str) -> None:
    if not re.fullmatch(r"(manual|automatic)-\d{8}-\d{6}-[a-z0-9]+|backup-\d+", value):
        raise ValueError("INVALID_BACKUP_ID")


def backup_path(settings: Settings, backup_id_value: str) -> Path:
    assert_backup_id(backup_id_value)
    return backup_dir(settings) / f"{backup_id_value}.zip"


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=json_default).encode(
        "utf-8"
    )


def counts_for_export(
    database_export: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    return {
        "users": len(database_export.get("users", [])),
        "userPreferences": len(database_export.get("userPreferences", [])),
        "libraries": len(database_export.get("libraries", [])),
        "userLibraryAccess": len(database_export.get("userLibraryAccess", [])),
        "works": len(database_export.get("works", [])),
        "mediaVersions": len(database_export.get("mediaVersions", [])),
        "volumes": len(database_export.get("volumes", [])),
        "files": len(database_export.get("files", [])),
        "readingUnits": len(database_export.get("readingUnits", [])),
        "metadataItems": len(database_export.get("metadataItems", [])),
        "facets": len(database_export.get("facets", [])),
        "workFacets": len(database_export.get("workFacets", [])),
        "volumeFacets": len(database_export.get("volumeFacets", [])),
        "shelves": len(database_export.get("shelves", [])),
        "shelfWorks": len(database_export.get("shelfWorks", [])),
        "readingProgresses": len(database_export.get("readingProgresses", [])),
        "workDetailPreferences": len(database_export.get("workDetailPreferences", [])),
        "importTasks": len(database_export.get("importTasks", [])),
        "importAssets": len(database_export.get("importAssets", [])),
        "bookConversionTasks": len(database_export.get("bookConversionTasks", [])),
        "importLogs": len(database_export.get("importLogs", [])),
        "readerPreferences": len(database_export.get("readerPreferences", [])),
        "readerBookPreferences": len(database_export.get("readerBookPreferences", [])),
        "readerProgressCursors": len(database_export.get("readerProgressCursors", [])),
        "readerBookmarks": len(database_export.get("readerBookmarks", [])),
        "mediaVersionMigrationEvents": len(
            database_export.get("mediaVersionMigrationEvents", [])
        ),
        "sources": len(database_export.get("sources", [])),
        "metadataProviderPipelines": len(
            database_export.get("metadataProviderPipelines", [])
        ),
        "systemSettings": len(database_export.get("systemSettings", [])),
        "coverIndexEntries": len(database_export.get("coverIndex", [])),
    }


def current_database_revision(db: Session) -> str:
    revision = MigrationContext.configure(db.connection()).get_current_revision()
    if revision is None:
        raise RuntimeError("database has no Alembic revision")
    return revision


def _engine_for_session(db: Session) -> Engine:
    bind = db.get_bind()
    if not isinstance(bind, Engine):
        raise TypeError("backup restore requires an Engine-bound Session")
    return bind


def _engine_database_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    if revision is None:
        raise RuntimeError("database has no Alembic revision")
    return revision


def create_backup(
    db: Session, settings: Settings, kind: str = "manual"
) -> BackupResult:
    if kind != "manual":
        raise ValueError("BACKUP_KIND_UNSUPPORTED")
    created_at = datetime.now(UTC)
    backup_id_value = backup_id(kind, created_at)
    database_export = {
        export_key: fetch_table(db, table) for export_key, table in BACKUP_TABLES
    }
    database_revision = current_database_revision(db)
    db.close()
    database_export["coverIndex"] = [
        {
            "workId": work.get("id"),
            "coverPath": work.get("coverPath"),
            "coverStatus": work.get("coverStatus"),
        }
        for work in database_export.get("works", [])
    ]
    counts = counts_for_export(database_export)
    counts["libraryFiles"] = 0
    metadata = {
        "id": backup_id_value,
        "kind": kind,
        "app": "ermao-books",
        "version": 3,
        "databaseRevision": database_revision,
        "createdAt": created_at.isoformat(),
        "format": "zip",
        "contents": ["metadata.json", "database-export.json", "settings.json"],
        "scope": [
            "database-v3",
            "system-settings",
            "library-metadata",
            "reading-metadata",
            "tags",
            "volume-progress",
            "library-settings",
            "multi-user-authorization",
            "user-preferences",
            "reader-bookmarks",
            "cover-cache-index",
        ],
        "excludes": [
            "reader-content-files",
            "publication-render-cache",
            "cover-image-files",
            "library-files/",
        ],
        "counts": counts,
    }
    settings_export = {
        "libraries": database_export.get("libraries", []),
        "systemSettings": database_export.get("systemSettings", []),
        "storageRoot": str(settings.resolved_storage_root),
        "backupRoot": str(backup_dir(settings)),
        "backupMode": "manual",
    }
    path = backup_path(settings, backup_id_value)
    temporary_path = path.with_name(f".{path.name}.{token_hex(4)}.part")
    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr("metadata.json", json_bytes(metadata))
            archive.writestr("database-export.json", json_bytes(database_export))
            archive.writestr("settings.json", json_bytes(settings_export))
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    result = BackupResult(
        backup_id_value, path.name, path.stat().st_size, created_at.isoformat(), counts
    )
    return result


def read_backup_metadata(path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read("metadata.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
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
                "createdAt": metadata.get("createdAt")
                if metadata
                else datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                "counts": metadata.get("counts") if metadata else None,
            }
        )
    return sorted(
        backups, key=lambda item: str(item.get("createdAt") or ""), reverse=True
    )


def delete_backup_file(settings: Settings, backup_id_value: str) -> bool:
    path = backup_path(settings, backup_id_value)
    if not path.exists():
        return False
    path.unlink()
    return True


def parse_backup(path: Path) -> tuple[dict[str, Any], dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
        database_export = json.loads(
            archive.read("database-export.json").decode("utf-8")
        )
    if not isinstance(metadata, dict) or not isinstance(database_export, dict):
        raise BackupFormatError("BACKUP_FORMAT_INVALID")
    if metadata.get("app") != "ermao-books" or metadata.get("version") != 3:
        raise ValueError("BACKUP_REVISION_UNSUPPORTED")
    return metadata, database_export


def _calibrate_runtime_rows(
    table_name: str,
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Release restored in-flight leases without creating OPF history work."""

    result: list[dict[str, object]] = []
    for source_record in records:
        record = dict(source_record)
        status = record.get("status")
        if table_name == "ImportTask" and status == "PARSING":
            record.update(
                status="PENDING",
                leaseOwner=None,
                leaseExpiresAt=None,
            )
        elif table_name == "MetadataLookupTask" and status == "RUNNING":
            record.update(
                status="PENDING",
                leaseOwnerId=None,
                leaseExpiresAt=None,
                startedAt=None,
            )
        elif table_name == "BookConversionTask" and status == "RUNNING":
            record.update(status="QUEUED", startedAt=None)
        elif table_name == "OrganizeJob" and status == "RUNNING":
            record.update(status="PENDING", startedAt=None)
        result.append(record)
    return tuple(result)


def _prepare_restore(
    database_export: dict[str, object],
) -> PreparedRestorePlan:
    records_by_table: dict[str, tuple[dict[str, object], ...]] = {}
    for export_key, table_name in BACKUP_TABLES:
        records = _calibrate_runtime_rows(
            table_name,
            prepare_table_records(table_name, database_export.get(export_key, [])),
        )
        if table_name == "SystemSetting":
            records = tuple(
                record
                for record in records
                if record.get("key") != DATABASE_MAINTENANCE_SETTING_KEY
            )
        records_by_table[table_name] = records
    validate_restore_relationships(records_by_table)
    return prepare_restore_plan(
        delete_order=tuple(RESTORE_ORDER),
        insertion_order=tuple(BACKUP_TABLES),
        records_by_table=records_by_table,
        maintenance_setting_key=DATABASE_MAINTENANCE_SETTING_KEY,
    )


def _validate_restore_against_temporary_database(
    plan: PreparedRestorePlan,
) -> None:
    with tempfile.TemporaryDirectory(prefix="shuku-restore-validation-") as directory:
        validation_settings = Settings(storage_root=str(Path(directory) / "storage"))
        validation_engine = create_sqlite_engine(validation_settings.database_path)
        try:
            bootstrap_database(validation_engine, validation_settings)
            with Session(validation_engine) as validation_db:
                ApplyValidatedBackupRestore(
                    SqlAlchemyBackupRestoreWriter(validation_db),
                    validation_db,
                ).execute(plan)
        finally:
            validation_engine.dispose()


def restore_backup(
    db: Session, settings: Settings, backup_id_value: str
) -> dict[str, Any]:
    path = backup_path(settings, backup_id_value)
    if not path.exists():
        raise FileNotFoundError("备份不存在")
    metadata, database_export = parse_backup(path)
    live_engine = _engine_for_session(db)
    supported_revision = head_revision(live_engine)
    if (
        metadata.get("databaseRevision") != supported_revision
        or _engine_database_revision(live_engine) != supported_revision
    ):
        raise ValueError("BACKUP_REVISION_UNSUPPORTED")
    plan = _prepare_restore(database_export)
    _validate_restore_against_temporary_database(plan)
    writer = SqlAlchemyBackupRestoreWriter(db)
    ApplyValidatedBackupRestore(writer, db).execute(
        prepare_maintenance_state_plan(
            setting_key=DATABASE_MAINTENANCE_SETTING_KEY,
            setting_value=DATABASE_MAINTENANCE_RESTORE_VALUE,
        )
    )
    try:
        with (
            database_restore_barrier(settings.database_path),
            database_restore_connection(db.connection()),
        ):
            try:
                ApplyValidatedBackupRestore(writer, db).execute(plan)
            except Exception:
                ApplyValidatedBackupRestore(writer, db).execute(
                    prepare_maintenance_state_plan(
                        setting_key=DATABASE_MAINTENANCE_SETTING_KEY,
                        setting_value=None,
                    )
                )
                raise
    except Exception:
        ApplyValidatedBackupRestore(writer, db).execute(
            prepare_maintenance_state_plan(
                setting_key=DATABASE_MAINTENANCE_SETTING_KEY,
                setting_value=None,
            )
        )
        raise
    db.expire_all()
    actual_counts = {
        export_key: len(fetch_table(db, table)) for export_key, table in BACKUP_TABLES
    }
    db.close()
    return {
        "id": backup_id_value,
        "restored": True,
        "restoredAt": datetime.now(UTC).isoformat(),
        "counts": metadata.get("counts"),
        "restoredCounts": plan.restored_counts,
        "actualCounts": actual_counts,
    }
