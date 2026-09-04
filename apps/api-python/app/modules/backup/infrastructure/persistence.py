"""ORM persistence for backup export and restore."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Table,
    Text,
    delete,
    insert,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapper, Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.core.time import TimestampMilliseconds
from app.db.base import Base
from app.models import (
    BookDetailPreference,
    ExternalMetadataCache,
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryImportTask,
    LibraryOperation,
    LibraryReadableResource,
    LibraryReadableResourceFacet,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
    LibrarySourceNodeMetadata,
    MetadataLookupTask,
    MetadataSuggestion,
    OrganizeJob,
    OrganizeRun,
    ReadableResourceNavigationUnit,
    ReaderBookmark,
    ReaderBookmarkV5,
    ReaderBookPreference,
    ReaderPreference,
    ReaderProgressCursor,
    ReaderProgressMutation,
    ReaderProgressMutationV5,
    ReaderResourceProgress,
    ReaderResourceProgressV5,
    ReaderResourceReadingStatusV5,
    Shelf,
    ShelfBook,
    ShelfCollectionMembership,
    Source,
    SystemSetting,
    User,
    UserLibraryAccess,
    UserPreference,
)
from app.models.common import db_timestamp
from app.modules.backup.application.restore import (
    BackupRecordValidationError,
    MaintenanceStateChange,
    PreparedRestorePlan,
    RestoreTableBatch,
)


def _legacy_column_to_attr(model: type[Base]) -> dict[str, str]:
    mapper = cast(Mapper[Any], sa_inspect(model))
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


TABLE_MODELS: dict[str, type[Base]] = {
    "User": User,
    "UserPreference": UserPreference,
    "Shelf": Shelf,
    "ShelfCollectionMembership": ShelfCollectionMembership,
    "Library": Library,
    "UserLibraryAccess": UserLibraryAccess,
    "LibraryBook": LibraryBook,
    "LibraryReadableResource": LibraryReadableResource,
    "LibraryResourceAsset": LibraryResourceAsset,
    "LibraryResourceAssetMetadata": LibraryResourceAssetMetadata,
    "LibrarySourceNode": LibrarySourceNode,
    "LibrarySourceNodeMetadata": LibrarySourceNodeMetadata,
    "LibrarySourceNodeInterpretation": LibrarySourceNodeInterpretation,
    "LibraryBookMetadata": LibraryBookMetadata,
    "LibraryReadableResourceMetadata": LibraryReadableResourceMetadata,
    "LibraryFacet": LibraryFacet,
    "LibraryBookFacet": LibraryBookFacet,
    "LibraryReadableResourceFacet": LibraryReadableResourceFacet,
    "ShelfBook": ShelfBook,
    "ReaderResourceProgress": ReaderResourceProgress,
    "ReaderResourceProgressV5": ReaderResourceProgressV5,
    "ReaderResourceReadingStatusV5": ReaderResourceReadingStatusV5,
    "ReaderBookmarkV5": ReaderBookmarkV5,
    "BookDetailPreference": BookDetailPreference,
    "ReadableResourceNavigationUnit": ReadableResourceNavigationUnit,
    "LibraryImportTask": LibraryImportTask,
    "OrganizeJob": OrganizeJob,
    "OrganizeRun": OrganizeRun,
    "MetadataSuggestion": MetadataSuggestion,
    "MetadataLookupTask": MetadataLookupTask,
    "ExternalMetadataCache": ExternalMetadataCache,
    "ReaderPreference": ReaderPreference,
    "ReaderBookPreference": ReaderBookPreference,
    "ReaderProgressCursor": ReaderProgressCursor,
    "ReaderBookmark": ReaderBookmark,
    "ReaderProgressMutation": ReaderProgressMutation,
    "ReaderProgressMutationV5": ReaderProgressMutationV5,
    "LibraryOperation": LibraryOperation,
    "Source": Source,
    "SystemSetting": SystemSetting,
}


def table_dependency_order(table_names: Iterable[str]) -> tuple[str, ...]:
    """Return a stable parent-before-child order for the selected ORM tables.

    SQLAlchemy's metadata is the source of truth for ownership.  Keeping the
    order derived from foreign keys prevents a newly-added child table from
    silently being inserted before its parent in a backup restore.  Self
    references (the SourceNode parent tree) are resolved at row level by
    ``_row_dependency_order`` below.
    """

    ordered_names = tuple(dict.fromkeys(table_names))
    selected = set(ordered_names)
    dependencies: dict[str, set[str]] = {name: set() for name in ordered_names}
    for table_name in ordered_names:
        model = TABLE_MODELS.get(table_name)
        if model is None:
            continue
        table = cast(Table, model.__table__)
        for constraint in table.foreign_key_constraints:
            parent_table = constraint.referred_table.name
            if parent_table in selected and parent_table != table_name:
                dependencies[table_name].add(parent_table)

    result: list[str] = []
    remaining = set(ordered_names)
    while remaining:
        ready = [
            name
            for name in ordered_names
            if name in remaining and not (dependencies[name] & remaining)
        ]
        if not ready:
            raise BackupRecordValidationError("BACKUP_TABLE_DEPENDENCY_CYCLE")
        result.extend(ready)
        remaining.difference_update(ready)
    return tuple(result)


def model_columns(model: type[Base]) -> set[str]:
    return {column.name for column in model.__table__.columns}


def _entity_to_export_record(entity: object) -> dict[str, Any]:
    mapper = cast(Mapper[Any], sa_inspect(type(entity)))
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


def _legacy_to_model_values(
    model: type[Base], record: dict[str, Any]
) -> dict[str, Any]:
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
        if not isinstance(value, (str, bytes, bytearray, int, float)):
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
        if not isinstance(value, (str, bytes, bytearray, int, float)):
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


def _row_dependency_order(
    table_name: str,
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Order rows with a same-table parent FK before their children."""

    if table_name != "LibrarySourceNode" or not records:
        return records
    records_by_id = {
        record.get("id"): record for record in records if record.get("id") is not None
    }
    ordered: list[dict[str, object]] = []
    visiting: set[object] = set()
    visited: set[object] = set()

    def visit(record_id: object) -> None:
        if record_id in visited or record_id is None:
            return
        if record_id in visiting:
            raise BackupRecordValidationError(
                "BACKUP_ROW_DEPENDENCY_CYCLE:LibrarySourceNode"
            )
        record = records_by_id.get(record_id)
        if record is None:
            return
        visiting.add(record_id)
        visit(record.get("parentId"))
        visiting.remove(record_id)
        visited.add(record_id)
        ordered.append(record)

    for record in records:
        visit(record.get("id"))
    return tuple(ordered)


def validate_restore_relationships(
    records_by_table: dict[str, tuple[dict[str, object], ...]],
) -> None:
    """Reject duplicate identities and dangling exported foreign keys in memory."""

    for table_name, records in records_by_table.items():
        model = TABLE_MODELS.get(table_name)
        if model is None:
            raise BackupRecordValidationError(f"BACKUP_TABLE_UNKNOWN:{table_name}")
        primary_keys = tuple(column.name for column in model.__table__.primary_key)
        seen_primary_keys: set[tuple[object, ...]] = set()
        for record in records:
            primary_key = tuple(record.get(name) for name in primary_keys)
            if primary_keys and primary_key in seen_primary_keys:
                raise BackupRecordValidationError(
                    f"BACKUP_DUPLICATE_PRIMARY_KEY:{table_name}"
                )
            if primary_keys:
                seen_primary_keys.add(primary_key)

    for table_name, records in records_by_table.items():
        model = TABLE_MODELS[table_name]
        table = cast(Table, model.__table__)
        for constraint in table.foreign_key_constraints:
            target_table = constraint.referred_table.name
            target_records = records_by_table.get(target_table, ())
            target_columns = tuple(
                element.column.name for element in constraint.elements
            )
            target_values = {
                tuple(record.get(column_name) for column_name in target_columns)
                for record in target_records
            }
            local_columns = tuple(
                element.parent.name for element in constraint.elements
            )
            for record in records:
                values = tuple(record.get(column_name) for column_name in local_columns)
                # SQLite follows normal nullable-FK semantics for a composite
                # key: a NULL component means the relationship is not
                # asserted.  The SourceNode parent-pair CHECK constraint is
                # still enforced by the validation database before restore.
                if any(value is None for value in values):
                    continue
                if values not in target_values:
                    raise BackupRecordValidationError(
                        f"BACKUP_FOREIGN_KEY_INVALID:{table_name}.{local_columns[0]}"
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
    """Build an ORM-free immutable plan before the writer slot is acquired."""

    insertion_by_table = {
        table_name: export_key for export_key, table_name in insertion_order
    }
    insertion_tables = table_dependency_order(insertion_by_table)
    delete_tables = tuple(reversed(table_dependency_order(delete_order)))

    restored_counts: dict[str, int] = {}
    batches: list[RestoreTableBatch] = []
    for table_name in insertion_tables:
        export_key = insertion_by_table[table_name]
        records = _row_dependency_order(
            table_name, records_by_table.get(table_name, ())
        )
        restored_counts[export_key] = len(records)
        batches.append(
            RestoreTableBatch(
                export_key=export_key,
                table_name=table_name,
                records=records,
            )
        )
    restored_counts["libraryFiles"] = 0
    return PreparedRestorePlan(
        kind="database",
        restored_counts=restored_counts,
        delete_order=delete_tables,
        batches=tuple(batches),
        maintenance_setting_key=maintenance_setting_key,
    )


def prepare_maintenance_state_plan(
    *,
    setting_key: str,
    setting_value: str | None,
) -> PreparedRestorePlan:
    return PreparedRestorePlan(
        kind="maintenance",
        restored_counts={},
        maintenance_change=MaintenanceStateChange(
            setting_key=setting_key,
            setting_value=setting_value,
            changed_at=db_timestamp(),
        ),
    )


class SqlAlchemyBackupRestoreWriter:
    def __init__(
        self,
        db: Session,
        table_models: dict[str, type[Base]] | None = None,
    ) -> None:
        self._db = db
        self._table_models = table_models or TABLE_MODELS

    def apply(self, plan: PreparedRestorePlan) -> None:
        if plan.kind == "maintenance":
            self._apply_maintenance(plan)
            return
        for table_name in plan.delete_order:
            model = self._table_models.get(table_name)
            if model is not None:
                self._db.execute(delete(model))
        for batch in plan.batches:
            model = self._table_models.get(batch.table_name)
            if model is None:
                continue
            for keys, group in _record_groups(batch.records):
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
                        self._db.execute(
                            statement.on_conflict_do_update(
                                index_elements=[User.id],
                                set_=update_values,
                            )
                        )
                    else:
                        self._db.execute(insert(model).values(list(chunk)))
        if plan.maintenance_setting_key is not None:
            self._db.execute(
                delete(SystemSetting).where(
                    SystemSetting.key == plan.maintenance_setting_key
                )
            )

    def _apply_maintenance(self, plan: PreparedRestorePlan) -> None:
        change = plan.maintenance_change
        if change is None:
            raise BackupRecordValidationError("BACKUP_MAINTENANCE_PLAN_INVALID")
        if change.setting_value is None:
            self._db.execute(
                delete(SystemSetting).where(SystemSetting.key == change.setting_key)
            )
            return
        statement = (
            sqlite_insert(SystemSetting)
            .values(
                key=change.setting_key,
                value=change.setting_value,
                updated_at=change.changed_at,
            )
            .on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={
                    SystemSetting.value: change.setting_value,
                    SystemSetting.updated_at: change.changed_at,
                },
            )
        )
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
