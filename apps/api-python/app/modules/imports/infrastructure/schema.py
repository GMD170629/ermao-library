"""Schema introspection and legacy row mapping for import persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.import_pipeline import (
    BookConversionTask,
    DownloadTask,
    ImportAsset,
    ImportLog,
    ImportTask,
    Source,
    SourceSearchRecord,
)
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.settings import MonitorFolder, SystemSetting
from app.models.shelf import Shelf, ShelfWork

TABLE_MODELS: dict[str, type] = {
    "ImportTask": ImportTask,
    "ImportAsset": ImportAsset,
    "ImportLog": ImportLog,
    "BookConversionTask": BookConversionTask,
    "DownloadTask": DownloadTask,
    "Source": Source,
    "SourceSearchRecord": SourceSearchRecord,
    "MonitorFolder": MonitorFolder,
    "SystemSetting": SystemSetting,
    "Shelf": Shelf,
    "ShelfWork": ShelfWork,
    "LibraryWork": LibraryWork,
    "LibraryEdition": LibraryEdition,
    "LibraryVolume": LibraryVolume,
    "LibraryFile": LibraryFile,
    "LibraryReadingUnit": LibraryReadingUnit,
    "LibraryMetadata": LibraryMetadata,
    "LibraryReadingProgress": LibraryReadingProgress,
    "LibraryConsumptionState": LibraryConsumptionState,
    "OrganizeJob": OrganizeJob,
    "MetadataLookupTask": MetadataLookupTask,
}


def reflected_table(db: Session, table: str) -> Table:
    """Return a reflected Table, caching per DB connection to avoid PRAGMA storms."""

    connection = db.connection()
    cache: dict[str, Table] = connection.info.setdefault("_starship_reflected_tables", {})
    cached = cache.get(table)
    if cached is not None:
        return cached
    metadata = MetaData()
    reflected = Table(table, metadata, autoload_with=connection, resolve_fks=False)
    cache[table] = reflected
    return reflected


def has_table(db: Session, table: str) -> bool:
    connection = db.connection()
    cache: dict[str, bool] = connection.info.setdefault("_starship_has_table", {})
    if table in cache:
        return cache[table]
    present = sa_inspect(connection).has_table(table)
    cache[table] = present
    return present


def table_columns(db: Session, table: str) -> set[str]:
    connection = db.connection()
    cache: dict[str, set[str]] = connection.info.setdefault("_starship_table_columns", {})
    cached = cache.get(table)
    if cached is not None:
        return cached
    columns = {column["name"] for column in sa_inspect(connection).get_columns(table)}
    cache[table] = columns
    return columns


def model_for_table(table: str) -> type | None:
    return TABLE_MODELS.get(table)


def entity_as_legacy_dict(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key)
        for prop in mapper.column_attrs
    }


def legacy_row_to_attr_values(
    model: type,
    row: dict[str, Any],
    *,
    columns: set[str] | None = None,
) -> dict[str, Any]:
    name_to_key = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(model).mapper.column_attrs
    }
    values: dict[str, Any] = {}
    for name, value in row.items():
        if columns is not None and name not in columns:
            continue
        key = name_to_key.get(name)
        if key is not None:
            values[key] = value
    return values
