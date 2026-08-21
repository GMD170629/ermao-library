"""Prepared commands for library catalog-root state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.library.domain.layout import LibraryOrganizationMode
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


class LibraryWriteStorePort(Protocol):
    def create(self, prepared: PreparedLibraryCreate) -> None: ...

    def update(self, prepared: PreparedLibraryUpdate) -> None: ...

    def delete(self, prepared: PreparedLibraryDelete) -> bool: ...


class LibraryWriteUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class CreateLibrary:
    def __init__(
        self,
        store: LibraryWriteStorePort,
        unit_of_work: LibraryWriteUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, prepared: PreparedLibraryCreate) -> None:
        try:
            self._store.create(prepared)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise


class UpdateLibrary:
    def __init__(
        self,
        store: LibraryWriteStorePort,
        unit_of_work: LibraryWriteUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, prepared: PreparedLibraryUpdate) -> None:
        try:
            self._store.update(prepared)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise


class DeleteLibrary:
    def __init__(
        self,
        store: LibraryWriteStorePort,
        unit_of_work: LibraryWriteUnitOfWork,
    ) -> None:
        self._store = store
        self._unit_of_work = unit_of_work

    def execute(self, prepared: PreparedLibraryDelete) -> bool:
        try:
            deleted = self._store.delete(prepared)
            self._unit_of_work.commit()
            return deleted
        except Exception:
            self._unit_of_work.rollback()
            raise


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
    prepared = {
        target: value
        for key, value in values.items()
        if (target := mapping.get(key)) is not None
    }
    mode = prepared.get("organization_mode")
    if mode is not None:
        prepared["organization_mode"] = LibraryOrganizationMode(mode).value
    return prepared
