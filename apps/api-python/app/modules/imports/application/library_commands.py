"""Prepared commands for library catalog-root state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.imports.application.ports import ImportUnitOfWork
from app.modules.system.public import PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedLibraryCreate:
    values: dict[str, object]
    event: PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedLibraryUpdate:
    library_id: str
    values: dict[str, object]
    event: PreparedSystemEvent


@dataclass(frozen=True, slots=True)
class PreparedLibraryDelete:
    library_id: str
    affected_user_ids: tuple[str, ...]
    updated_at: datetime
    event: PreparedSystemEvent


class LibraryWriteStore(Protocol):
    def create(self, prepared: PreparedLibraryCreate) -> None: ...

    def update(self, prepared: PreparedLibraryUpdate) -> None: ...

    def delete(self, prepared: PreparedLibraryDelete) -> bool: ...


def prepare_library_update_values(
    values: dict[str, object],
) -> dict[str, object]:
    mapping = {
        "name": "name",
        "rootPath": "root_path",
        "organizationMode": "organization_mode",
        "enabled": "enabled",
        "ignorePatterns": "ignore_patterns",
        "ignoreHidden": "ignore_hidden",
        "minFileSizeBytes": "min_file_size_bytes",
        "description": "description",
        "updatedAt": "updated_at",
    }
    return {
        target: value
        for key, value in values.items()
        if (target := mapping.get(key)) is not None
    }


def persist_library_create(
    store: LibraryWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedLibraryCreate,
) -> None:
    try:
        store.create(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def persist_library_update(
    store: LibraryWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedLibraryUpdate,
) -> None:
    try:
        store.update(prepared)
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise


def persist_library_delete(
    store: LibraryWriteStore,
    unit_of_work: ImportUnitOfWork,
    prepared: PreparedLibraryDelete,
) -> bool:
    try:
        deleted = store.delete(prepared)
        unit_of_work.commit()
        return deleted
    except Exception:
        unit_of_work.rollback()
        raise
