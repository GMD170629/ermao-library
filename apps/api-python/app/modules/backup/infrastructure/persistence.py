"""ORM persistence for backup export and restore."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import (
    BookConversionTask,
    BookIdentityCache,
    DuplicateCandidate,
    ExternalMetadataCache,
    ImportAsset,
    ImportLog,
    ImportTask,
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
    MediaVersionMigrationEvent,
    MetadataLookupTask,
    MetadataSuggestion,
    MonitorFolder,
    OrganizeJob,
    ReaderBookmark,
    ReaderBookPreference,
    ReaderPreference,
    ReaderProgressCursor,
    Shelf,
    ShelfWork,
    SystemSetting,
    User,
    UserMediaHistory,
    UserMonitorFolderAccess,
    UserPreference,
    WorkDetailPreference,
)


def _legacy_column_to_attr(model: type) -> dict[str, str]:
    mapper = sa_inspect(model)
    return {prop.columns[0].name: prop.key for prop in mapper.column_attrs}


TABLE_MODELS: dict[str, type] = {
    "User": User,
    "UserPreference": UserPreference,
    "Shelf": Shelf,
    "MonitorFolder": MonitorFolder,
    "UserMonitorFolderAccess": UserMonitorFolderAccess,
    "LibraryWork": LibraryWork,
    "LibraryMediaVersion": LibraryMediaVersion,
    "LibraryVolume": LibraryVolume,
    "LibraryFile": LibraryFile,
    "LibraryReadingUnit": LibraryReadingUnit,
    "LibraryMetadata": LibraryMetadata,
    "LibraryFacet": LibraryFacet,
    "LibraryWorkFacet": LibraryWorkFacet,
    "LibraryVolumeFacet": LibraryVolumeFacet,
    "ShelfWork": ShelfWork,
    "LibraryReadingProgress": LibraryReadingProgress,
    "UserMediaHistory": UserMediaHistory,
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


def insert_records(db: Session, table: str, records: list[dict[str, Any]]) -> int:
    model = TABLE_MODELS.get(table)
    if not records or model is None:
        return 0
    inserted = 0
    for record in records:
        values = _legacy_to_model_values(model, record)
        if not values:
            continue
        db.add(model(**values))
        inserted += 1
    db.flush()
    return inserted


def upsert_user_records(db: Session, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    restored = 0
    for record in records:
        values = _legacy_to_model_values(User, record)
        if not values:
            continue
        existing_id = None
        if values.get("id"):
            existing_id = db.scalar(select(User.id).where(User.id == values["id"]))
        if not existing_id and values.get("email"):
            existing_id = db.scalar(
                select(User.id).where(User.email == values["email"])
            )
        if existing_id:
            user = db.get(User, existing_id)
            if user is not None:
                for key, value in values.items():
                    if key != "id":
                        setattr(user, key, value)
                restored += 1
            continue
        db.add(User(**values))
        restored += 1
    db.flush()
    return restored


def clear_table_if_present(db: Session, table: str) -> None:
    model = TABLE_MODELS.get(table)
    if model is None:
        return
    db.execute(delete(model))
