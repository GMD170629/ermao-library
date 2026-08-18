"""ORM persistence for backup export and restore."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    delete,
    insert,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import TimestampMilliseconds
from app.models import (
    BookConversionTask,
    BookIdentityCache,
    DuplicateCandidate,
    ExternalMetadataCache,
    ImportAsset,
    ImportLog,
    ImportTask,
    Library,
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
    MediaVersionMigrationEvent,
    MetadataLookupTask,
    MetadataProviderPipeline,
    MetadataSuggestion,
    OrganizeJob,
    ReaderBookmark,
    ReaderBookPreference,
    ReaderPreference,
    ReaderProgressCursor,
    Shelf,
    ShelfWork,
    Source,
    SystemSetting,
    User,
    UserLibraryAccess,
    UserPreference,
    WorkDetailPreference,
)
from app.models.common import db_timestamp
from app.modules.backup.application.restore import (
    BackupRecordValidationError,
    PreparedRestorePlan,
)


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


TABLE_MODELS: dict[str, type] = {
    "User": User,
    "UserPreference": UserPreference,
    "Shelf": Shelf,
    "Library": Library,
    "UserLibraryAccess": UserLibraryAccess,
    "LibraryWork": LibraryWork,
    "LibraryMediaVersion": LibraryMediaVersion,
    "LibraryVersion": LibraryVersion,
    "LibraryVolume": LibraryVolume,
    "LibraryFile": LibraryFile,
    "LibraryReadingUnit": LibraryReadingUnit,
    "LibraryMetadata": LibraryMetadata,
    "LibraryFacet": LibraryFacet,
    "LibraryWorkFacet": LibraryWorkFacet,
    "LibraryVolumeFacet": LibraryVolumeFacet,
    "ShelfWork": ShelfWork,
    "LibraryReadingProgress": LibraryReadingProgress,
    "WorkDetailPreference": WorkDetailPreference,
    "ImportTask": ImportTask,
    "ImportAsset": ImportAsset,
    "BookConversionTask": BookConversionTask,
    "ImportLog": ImportLog,
    "OrganizeJob": OrganizeJob,
    "MetadataSuggestion": MetadataSuggestion,
    "DuplicateCandidate": DuplicateCandidate,
    "MetadataLookupTask": MetadataLookupTask,
    "ExternalMetadataCache": ExternalMetadataCache,
    "BookIdentityCache": BookIdentityCache,
    "ReaderPreference": ReaderPreference,
    "ReaderBookPreference": ReaderBookPreference,
    "ReaderProgressCursor": ReaderProgressCursor,
    "ReaderBookmark": ReaderBookmark,
    "MediaVersionMigrationEvent": MediaVersionMigrationEvent,
    "Source": Source,
    "MetadataProviderPipeline": MetadataProviderPipeline,
    "SystemSetting": SystemSetting,
}


def model_columns(model: type) -> set[str]:
    return {column.name for column in model.__table__.columns}


def _entity_to_export_record(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def fetch_table(db: Session, table: str) -> list[dict[str, Any]]:
    model = TABLE_MODELS.get(table)
    if model is None:
        return []
    stmt = select(model)
    created_at = getattr(model, "created_at", None)
    if created_at is not None:
        stmt = stmt.order_by(created_at.asc())
    return [_entity_to_export_record(entity) for entity in db.scalars(stmt).all()]


def _legacy_to_model_values(model: type, record: dict[str, Any]) -> dict[str, Any]:
    allowed = model_columns(model)
    name_to_attr = _legacy_column_to_attr(model)
    return {
        name_to_attr[key]: value
        for key, value in record.items()
        if key in allowed and key in name_to_attr
    }


def _converted_column_value(column: Any, value: object) -> object:
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, (DateTime, TimestampMilliseconds)):
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            )
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            ) from exc
    if isinstance(column_type, Boolean):
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        raise BackupRecordValidationError(
            f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
        )
    if isinstance(column_type, Integer):
        if isinstance(value, bool):
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            )
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            ) from exc
    if isinstance(column_type, Float):
        if isinstance(value, bool):
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            )
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise BackupRecordValidationError(
                f"BACKUP_FIELD_TYPE_INVALID:{column.table.name}.{column.name}"
            ) from exc
    if isinstance(column_type, (String, Text)):
        return value if isinstance(value, str) else str(value)
    return value


def prepare_table_records(
    table: str,
    records: object,
) -> tuple[dict[str, object], ...]:
    """Filter and convert untrusted JSON records before any write transaction."""

    model = TABLE_MODELS.get(table)
    if model is None:
        return ()
    if not isinstance(records, list):
        raise BackupRecordValidationError(f"BACKUP_TABLE_INVALID:{table}")
    columns = {column.name: column for column in model.__table__.columns}
    prepared: list[dict[str, object]] = []
    for raw_record in records:
        if not isinstance(raw_record, dict):
            raise BackupRecordValidationError(f"BACKUP_RECORD_INVALID:{table}")
        record = {
            name: _converted_column_value(columns[name], value)
            for name, value in raw_record.items()
            if name in columns
        }
        if record:
            prepared.append(record)
    return tuple(prepared)


def validate_restore_relationships(
    records_by_table: dict[str, tuple[dict[str, object], ...]],
) -> None:
    """Reject duplicate identities and dangling exported foreign keys in memory."""

    referenced_columns = {
        (foreign_key.column.table.name, foreign_key.column.name)
        for model in TABLE_MODELS.values()
        for foreign_key in model.__table__.foreign_keys
    }
    values_by_column: dict[tuple[str, str], set[object]] = defaultdict(set)
    for table_name, records in records_by_table.items():
        model = TABLE_MODELS[table_name]
        primary_keys = tuple(column.name for column in model.__table__.primary_key)
        seen_primary_keys: set[tuple[object, ...]] = set()
        for record in records:
            primary_key = tuple(record.get(name) for name in primary_keys)
            if primary_keys and primary_key in seen_primary_keys:
                raise ValueError(f"BACKUP_DUPLICATE_PRIMARY_KEY:{table_name}")
            if primary_keys:
                seen_primary_keys.add(primary_key)
            for name, value in record.items():
                if value is not None and (table_name, name) in referenced_columns:
                    values_by_column[(table_name, name)].add(value)

    exported_tables = set(records_by_table)
    for table_name, records in records_by_table.items():
        model = TABLE_MODELS[table_name]
        for foreign_key in model.__table__.foreign_keys:
            target_table = foreign_key.column.table.name
            if target_table not in exported_tables:
                continue
            target_values = values_by_column[(target_table, foreign_key.column.name)]
            for record in records:
                value = record.get(foreign_key.parent.name)
                if value is not None and value not in target_values:
                    raise ValueError(
                        "BACKUP_FOREIGN_KEY_INVALID:"
                        f"{table_name}.{foreign_key.parent.name}"
                    )


def _record_groups(
    records: tuple[dict[str, object], ...],
) -> tuple[tuple[tuple[str, ...], list[dict[str, object]]], ...]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[tuple(sorted(record))].append(record)
    return tuple(grouped.items())


def prepare_restore_plan(
    *,
    delete_order: tuple[str, ...],
    insertion_order: tuple[tuple[str, str], ...],
    records_by_table: dict[str, tuple[dict[str, object], ...]],
    maintenance_setting_key: str | None = None,
) -> PreparedRestorePlan:
    """Construct all typed SQL and chunks before the writer slot is acquired."""

    statements: list[Any] = []
    for table_name in delete_order:
        model = TABLE_MODELS.get(table_name)
        if model is not None:
            statements.append(delete(model))

    restored_counts: dict[str, int] = {}
    for export_key, table_name in insertion_order:
        model = TABLE_MODELS.get(table_name)
        records = records_by_table.get(table_name, ())
        restored_counts[export_key] = len(records)
        if model is None:
            continue
        for keys, group in _record_groups(records):
            for chunk in sqlite_parameter_chunks(
                group,
                parameters_per_row=max(1, len(keys)),
            ):
                if model is User:
                    statement = sqlite_insert(User).values(list(chunk))
                    update_values = {
                        column.key: getattr(statement.excluded, column.key)
                        for column in User.__table__.columns
                        if not column.primary_key and column.name in keys
                    }
                    statements.append(
                        statement.on_conflict_do_update(
                            index_elements=[User.id],
                            set_=update_values,
                        )
                    )
                else:
                    statements.append(insert(model).values(list(chunk)))
    if maintenance_setting_key is not None:
        statements.append(
            delete(SystemSetting).where(SystemSetting.key == maintenance_setting_key)
        )
    restored_counts["libraryFiles"] = 0
    return PreparedRestorePlan(tuple(statements), restored_counts)


def prepare_maintenance_state_plan(
    *,
    setting_key: str,
    setting_value: str | None,
) -> PreparedRestorePlan:
    if setting_value is None:
        statement = delete(SystemSetting).where(SystemSetting.key == setting_key)
    else:
        timestamp = db_timestamp()
        statement = (
            sqlite_insert(SystemSetting)
            .values(key=setting_key, value=setting_value, updated_at=timestamp)
            .on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={
                    SystemSetting.value: setting_value,
                    SystemSetting.updated_at: timestamp,
                },
            )
        )
    return PreparedRestorePlan((statement,), {})


class SqlAlchemyBackupRestoreWriter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def apply(self, plan: PreparedRestorePlan) -> None:
        for statement in plan.statements:
            self._db.execute(statement)


def insert_records(db: Session, table: str, records: list[dict[str, Any]]) -> int:
    model = TABLE_MODELS.get(table)
    if not records or model is None:
        return 0
    prepared = prepare_table_records(table, records)
    for keys, group in _record_groups(prepared):
        for chunk in sqlite_parameter_chunks(
            group, parameters_per_row=max(1, len(keys))
        ):
            db.execute(insert(model).values(list(chunk)))
    return len(prepared)


def upsert_user_records(db: Session, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    prepared = prepare_table_records("User", records)
    for keys, group in _record_groups(prepared):
        for chunk in sqlite_parameter_chunks(
            group, parameters_per_row=max(1, len(keys))
        ):
            statement = sqlite_insert(User).values(list(chunk))
            update_values = {
                column.key: getattr(statement.excluded, column.key)
                for column in User.__table__.columns
                if not column.primary_key and column.name in keys
            }
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=[User.id], set_=update_values
                )
            )
    return len(prepared)


def clear_table_if_present(db: Session, table: str) -> None:
    model = TABLE_MODELS.get(table)
    if model is None:
        return
    db.execute(delete(model))
