from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import Any, BinaryIO

from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exception_diagnostics import capture_exception, record_exception
from app.db.bootstrap import bootstrap_database
from app.db.diagnostic_session import DiagnosticSession
from app.db.maintenance import (
    DATABASE_MAINTENANCE_RESTORE_VALUE,
    DATABASE_MAINTENANCE_SETTING_KEY,
    database_restore_barrier,
    database_restore_connection,
)
from app.db.runner import head_revision
from app.db.sqlite import create_sqlite_engine
from app.modules.backup.application.operations import (
    BackupOperationError,
    BackupRequestError,
)
from app.modules.backup.application.restore import (
    ApplyValidatedBackupRestore,
    PreparedRestorePlan,
)
from app.modules.backup.infrastructure.inspection import (
    BACKUP_FORMAT_VERSION,
    inspect_backup,
    require_compatible,
)
from app.modules.backup.infrastructure.persistence import (
    SqlAlchemyBackupRestoreWriter,
    fetch_table,
    prepare_maintenance_state_plan,
    prepare_restore_plan,
    prepare_table_records,
    validate_restore_relationships,
)
from app.modules.backup.infrastructure.problems import (
    backup_stage,
    failure_problem,
    problem,
)

BACKUP_TABLES: list[tuple[str, str]] = [
    ("users", "User"),
    ("userPreferences", "UserPreference"),
    ("shelves", "Shelf"),
    ("shelfCollectionMemberships", "ShelfCollectionMembership"),
    ("libraries", "Library"),
    ("sourceNodes", "LibrarySourceNode"),
    ("sourceNodeMetadata", "LibrarySourceNodeMetadata"),
    ("sourceNodeInterpretations", "LibrarySourceNodeInterpretation"),
    ("userLibraryAccess", "UserLibraryAccess"),
    ("books", "LibraryBook"),
    ("bookMetadata", "LibraryBookMetadata"),
    ("resources", "LibraryReadableResource"),
    ("resourceMetadata", "LibraryReadableResourceMetadata"),
    ("assets", "LibraryResourceAsset"),
    ("resourceAssetMetadata", "LibraryResourceAssetMetadata"),
    ("navigationUnits", "ReadableResourceNavigationUnit"),
    ("facets", "LibraryFacet"),
    ("bookFacets", "LibraryBookFacet"),
    ("resourceFacets", "LibraryReadableResourceFacet"),
    ("shelfBooks", "ShelfBook"),
    ("readerProgress", "ReaderResourceProgress"),
    ("readerProgressV5", "ReaderResourceProgressV5"),
    ("readerReadingStatusV5", "ReaderResourceReadingStatusV5"),
    ("readerBookmarksV5", "ReaderBookmarkV5"),
    ("bookPreferences", "BookDetailPreference"),
    ("importTasks", "LibraryImportTask"),
    ("organizeJobs", "OrganizeJob"),
    ("organizeRuns", "OrganizeRun"),
    ("metadataSuggestions", "MetadataSuggestion"),
    ("metadataLookupTasks", "MetadataLookupTask"),
    ("externalMetadataCache", "ExternalMetadataCache"),
    ("readerPreferences", "ReaderPreference"),
    ("readerBookPreferences", "ReaderBookPreference"),
    ("readerProgressCursors", "ReaderProgressCursor"),
    ("readerBookmarks", "ReaderBookmark"),
    ("readerProgressMutations", "ReaderProgressMutation"),
    ("readerProgressMutationsV5", "ReaderProgressMutationV5"),
    ("libraryOperations", "LibraryOperation"),
    ("sources", "Source"),
    ("systemSettings", "SystemSetting"),
]


# The persistence adapter derives the actual order from ORM foreign keys.  This
# list deliberately contains every exported table so the delete side clears
# the same complete scope before inserting the parent-before-child projection.
RESTORE_ORDER = [table_name for _export_key, table_name in BACKUP_TABLES]


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
    date = created_at or datetime.now(UTC)
    return f"{kind}-{date.strftime('%Y%m%d-%H%M%S')}-{token_hex(3)}"


def assert_backup_id(value: str) -> None:
    # IDs are filename stems, including user-uploaded names and collision indices.
    if (
        not value
        or value in {".", ".."}
        or value.startswith(".")
        or value.endswith((" ", "."))
        or re.search(r'[\x00-\x1f<>:"/\\|?*]', value)
        or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value)
    ):
        raise BackupOperationError(
            problem("BACKUP_NAME_INVALID", "备份文件名无效", "Invalid backup filename"),
            stage="file",
        )


def backup_path(settings: Settings, backup_id_value: str) -> Path:
    assert_backup_id(backup_id_value)
    root = backup_dir(settings).resolve()
    path = root / f"{backup_id_value}.zip"
    if path.is_symlink() or path.resolve().parent != root:
        raise BackupOperationError(
            problem(
                "BACKUP_PATH_INVALID", "备份文件路径不安全", "Unsafe backup file path"
            ),
            stage="file",
        )
    return path


def upload_backup(settings: Settings, filename: str, stream: BinaryIO) -> Path:
    if not filename.endswith(".zip"):
        raise BackupOperationError(
            problem(
                "BACKUP_EXTENSION_INVALID",
                "请选择 .zip 备份文件",
                "Select a .zip backup file",
            ),
            stage="upload",
        )
    stem = filename[:-4]
    backup_path(settings, stem)
    root = backup_dir(settings)
    temporary_path = root / f".upload-{token_hex(16)}.part"
    try:
        with temporary_path.open("xb") as output:
            while chunk := stream.read(1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        index = 0
        while True:
            candidate = backup_path(
                settings, stem if index == 0 else f"{stem}（{index}）"
            )
            try:
                # Atomic no-replace publication, on the same filesystem on Windows/Linux.
                os.link(temporary_path, candidate)
                break
            except FileExistsError as _caught_error:
                # diagnostics-control-flow: another upload owns this name; try the next index.
                capture_exception(_caught_error)
                index += 1
    except Exception as original:
        capture_exception(original, persist=False)
        record_exception(
            logging.getLogger(__name__),
            "backup.upload.failed",
            original,
        )
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as cleanup:
            capture_exception(cleanup, persist=False)
            record_exception(
                logging.getLogger(__name__),
                "backup.upload.cleanup_failed",
                cleanup,
            )
            raise ExceptionGroup(
                "Backup upload and cleanup failed", [original, cleanup]
            ) from original
        raise
    else:
        temporary_path.unlink(missing_ok=True)
        return candidate


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
        "books": len(database_export.get("books", [])),
        "bookMetadata": len(database_export.get("bookMetadata", [])),
        "resources": len(database_export.get("resources", [])),
        "resourceMetadata": len(database_export.get("resourceMetadata", [])),
        "assets": len(database_export.get("assets", [])),
        "navigationUnits": len(database_export.get("navigationUnits", [])),
        "facets": len(database_export.get("facets", [])),
        "bookFacets": len(database_export.get("bookFacets", [])),
        "resourceFacets": len(database_export.get("resourceFacets", [])),
        "shelves": len(database_export.get("shelves", [])),
        "shelfBooks": len(database_export.get("shelfBooks", [])),
        "readerProgress": len(database_export.get("readerProgress", [])),
        "readerProgressV5": len(database_export.get("readerProgressV5", [])),
        "readerReadingStatusV5": len(database_export.get("readerReadingStatusV5", [])),
        "readerBookmarksV5": len(database_export.get("readerBookmarksV5", [])),
        "bookPreferences": len(database_export.get("bookPreferences", [])),
        "importTasks": len(database_export.get("importTasks", [])),
        "readerPreferences": len(database_export.get("readerPreferences", [])),
        "readerBookPreferences": len(database_export.get("readerBookPreferences", [])),
        "readerProgressCursors": len(database_export.get("readerProgressCursors", [])),
        "readerBookmarks": len(database_export.get("readerBookmarks", [])),
        "readerProgressMutations": len(
            database_export.get("readerProgressMutations", [])
        ),
        "readerProgressMutationsV5": len(
            database_export.get("readerProgressMutationsV5", [])
        ),
        "sourceNodes": len(database_export.get("sourceNodes", [])),
        "sourceNodeMetadata": len(database_export.get("sourceNodeMetadata", [])),
        "sourceNodeInterpretations": len(
            database_export.get("sourceNodeInterpretations", [])
        ),
        "resourceAssetMetadata": len(database_export.get("resourceAssetMetadata", [])),
        "shelfCollectionMemberships": len(
            database_export.get("shelfCollectionMemberships", [])
        ),
        "organizeRuns": len(database_export.get("organizeRuns", [])),
        "libraryOperations": len(database_export.get("libraryOperations", [])),
        "sources": len(database_export.get("sources", [])),
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
        raise BackupRequestError("BACKUP_KIND_UNSUPPORTED")
    created_at = datetime.now(UTC)
    backup_id_value = backup_id(kind, created_at)
    database_export = {
        export_key: fetch_table(db, table) for export_key, table in BACKUP_TABLES
    }
    database_revision = current_database_revision(db)
    db.close()
    database_export["coverIndex"] = [
        {
            "bookId": book.get("id"),
            "coverPath": book.get("coverPath"),
            "coverStatus": book.get("coverStatus"),
        }
        for book in database_export.get("books", [])
    ]
    counts = counts_for_export(database_export)
    counts["managedAssets"] = len(database_export.get("assets", []))
    metadata = {
        "id": backup_id_value,
        "kind": kind,
        "app": "ermao-books",
        "version": BACKUP_FORMAT_VERSION,
        "databaseRevision": database_revision,
        "createdAt": created_at.isoformat(),
        "format": "zip",
        "contents": ["metadata.json", "database-export.json", "settings.json"],
        "scope": [
            "database-v5",
            "system-settings",
            "library-metadata",
            "reading-metadata",
            "tags",
            "resource-progress",
            "library-settings",
            "multi-user-authorization",
            "user-preferences",
            "reader-bookmarks",
            "cover-cache-index",
        ],
        "excludes": [
            "reader-content-assets",
            "publication-render-cache",
            "cover-image-assets",
            "managed-assets/",
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


def backup_record(path: Path, required_revision: str) -> dict[str, Any]:
    inspected = inspect_backup(path, required_revision)
    metadata = inspected.metadata
    try:
        stat = path.stat()
        size = stat.st_size
        created_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    except OSError as error:
        capture_exception(error, persist=False)
        record_exception(
            logging.getLogger(__name__),
            "backup.stat.failed",
            error,
        )
        inspected = replace(
            inspected,
            compatibility=replace(
                inspected.compatibility,
                status="unreadable",
                problem=failure_problem(error),
            ),
        )
        size = 0
        created_at = datetime.fromtimestamp(0, UTC).isoformat()
    if isinstance(metadata.get("createdAt"), str):
        try:
            created_at = datetime.fromisoformat(str(metadata["createdAt"])).isoformat()
        except ValueError as _caught_error:
            # diagnostics-control-flow: inspection already reports the invalid metadata.
            capture_exception(_caught_error)
    counts = metadata.get("counts")
    if not isinstance(counts, dict) or any(
        not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values()
    ):
        counts = None
    return {
        "id": path.stem,
        "kind": metadata.get("kind") or "unknown",
        "name": path.name,
        "filename": path.name,
        "sizeBytes": size,
        "createdAt": created_at,
        "counts": counts,
        "compatibility": inspected.compatibility,
    }


def list_backups(settings: Settings) -> list[dict[str, Any]]:
    revision = head_revision()
    backups = [
        backup_record(path, revision)
        for path in backup_dir(settings).glob("*.zip")
        if not path.is_symlink()
    ]
    return sorted(backups, key=lambda item: str(item["createdAt"]), reverse=True)


def delete_backup_file(settings: Settings, backup_id_value: str) -> bool:
    path = backup_path(settings, backup_id_value)
    if not path.exists():
        return False
    path.unlink()
    return True


def parse_backup(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    inspected = require_compatible(path, head_revision())
    try:
        with zipfile.ZipFile(path) as archive:
            database_export = json.loads(archive.read("database-export.json"))
    except (KeyError, ValueError, UnicodeError, zipfile.BadZipFile) as exc:
        capture_exception(exc, persist=False)
        raise BackupOperationError(
            problem(
                "BACKUP_DATA_INVALID",
                "database-export.json 无法读取或解析",
                "database-export.json cannot be read or parsed",
            ),
            stage="validate",
        ) from exc
    if not isinstance(database_export, dict):
        raise BackupOperationError(
            problem(
                "BACKUP_DATA_INVALID",
                "database-export.json 必须包含数据对象",
                "database-export.json must contain an object",
            ),
            stage="validate",
        )
    return inspected.metadata, database_export


def _calibrate_runtime_rows(
    table_name: str,
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Release restored metadata and organize jobs without creating history."""

    result: list[dict[str, object]] = []
    for source_record in records:
        record = dict(source_record)
        status = record.get("status")
        if table_name == "MetadataLookupTask" and status == "RUNNING":
            record.update(
                status="PENDING",
                leaseOwnerId=None,
                leaseExpiresAt=None,
                startedAt=None,
            )
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
            with DiagnosticSession(validation_engine) as validation_db:
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
        raise BackupOperationError(
            problem(
                "BACKUP_FILE_MISSING",
                "备份文件不存在",
                "The backup file does not exist",
            ),
            stage="restore",
            status_code=404,
        )
    with backup_stage("validate"):
        metadata, database_export = parse_backup(path)
    live_engine = _engine_for_session(db)
    supported_revision = head_revision(live_engine)
    if _engine_database_revision(live_engine) != supported_revision:
        raise BackupOperationError(
            problem(
                "BACKUP_LIVE_DATABASE_MISMATCH",
                "当前数据库尚未升级到应用要求的结构版本",
                "The live database has not been upgraded to the revision required by this application",
            ),
            stage="validate",
        )
    with backup_stage("validate"):
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
            ApplyValidatedBackupRestore(writer, db).execute(plan)
    except Exception as original:
        capture_exception(original, persist=False)
        record_exception(
            logging.getLogger(__name__),
            "backup.restore.apply_failed",
            original,
        )
        try:
            ApplyValidatedBackupRestore(writer, db).execute(
                prepare_maintenance_state_plan(
                    setting_key=DATABASE_MAINTENANCE_SETTING_KEY,
                    setting_value=None,
                )
            )
        except Exception as recovery:  # noqa: BLE001 - preserve the recovery failure alongside the original.
            capture_exception(recovery, persist=False)
            record_exception(
                logging.getLogger(__name__),
                "backup.restore.recovery_failed",
                recovery,
            )
            raise ExceptionGroup(
                "Backup restore and recovery failed", [original, recovery]
            ) from original
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
