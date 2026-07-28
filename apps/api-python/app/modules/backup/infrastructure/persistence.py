"""ORM persistence for backup export and restore."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, delete, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app.models import (
    BookConversionTask,
    BookIdentityCache,
    DuplicateCandidate,
    ExternalMetadataCache,
    ImportAsset,
    ImportLog,
    ImportTask,
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    MetadataLookupTask,
    MetadataSuggestion,
    MonitorFolder,
    OrganizeJob,
    ReaderBookPreference,
    ReaderBookmark,
    ReaderPreference,
    ReaderProgressCursor,
    Shelf,
    ShelfWork,
    SystemSetting,
    User,
    UserMonitorFolderAccess,
    UserPreference,
    WorkDetailPreference,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


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
    "LibraryEdition": LibraryEdition,
    "LibraryVolume": LibraryVolume,
    "LibraryFile": LibraryFile,
    "LibraryReadingUnit": LibraryReadingUnit,
    "LibraryMetadata": LibraryMetadata,
    "ShelfWork": ShelfWork,
    "LibraryReadingProgress": LibraryReadingProgress,
    "LibraryConsumptionState": LibraryConsumptionState,
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
    "SystemSetting": SystemSetting,
}


def table_names(db: Session) -> set[str]:
    return set(sa_inspect(db.get_bind()).get_table_names())


def model_columns(model: type) -> set[str]:
    return {column.name for column in model.__table__.columns}


def fetch_table(db: Session, table: str) -> list[dict[str, Any]]:
    if table not in table_names(db):
        return []
    metadata = MetaData()
    reflected = Table(table, metadata, autoload_with=db.get_bind())
    stmt = select(reflected)
    if "createdAt" in reflected.c:
        stmt = stmt.order_by(reflected.c.createdAt.asc())
    return [dict(row) for row in db.execute(stmt).mappings().all()]


def _legacy_to_model_values(model: type, record: dict[str, Any]) -> dict[str, Any]:
    allowed = model_columns(model)
    name_to_attr = _legacy_column_to_attr(model)
    return {
        name_to_attr[key]: value
        for key, value in record.items()
        if key in allowed and key in name_to_attr
    }


def insert_records(db: Session, table: str, records: list[dict[str, Any]]) -> int:
    if not records or table not in table_names(db):
        return 0
    reflected = Table(table, MetaData(), autoload_with=db.get_bind())
    allowed = {column.name for column in reflected.columns}
    inserted = 0
    for record in records:
        filtered = {key: value for key, value in record.items() if key in allowed}
        if not filtered:
            continue
        db.execute(reflected.insert().values(**filtered))
        inserted += 1
    db.commit()
    return inserted


def upsert_user_records(db: Session, records: list[dict[str, Any]]) -> int:
    if not records or "User" not in table_names(db):
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
            existing_id = db.scalar(select(User.id).where(User.email == values["email"]))
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
    db.commit()
    return restored


def clear_table_if_present(db: Session, table: str) -> None:
    model = TABLE_MODELS.get(table)
    if model is None or table not in table_names(db):
        return
    try:
        db.execute(delete(model))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
