from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class CatalogWork:
    id: uuid.UUID
    title: str
    author: str | None
    media_type: str
    status: str
    cover_key: str | None
    summary: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogEdition:
    id: uuid.UUID
    work_id: uuid.UUID
    title: str
    format: str
    language: str | None
    primary: bool
    metadata: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogFile:
    id: uuid.UUID
    edition_id: uuid.UUID
    storage_path: str
    original_name: str
    media_type: str
    size_bytes: int
    checksum: str
    volume_id: uuid.UUID | None = None
    sort_order: int = 0
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogVolume:
    id: uuid.UUID
    edition_id: uuid.UUID
    title: str
    sort_order: int
    page_count: int | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class CatalogEditionDetail:
    edition: CatalogEdition
    files: tuple[CatalogFile, ...]
    volumes: tuple[CatalogVolume, ...]


@dataclass(frozen=True, slots=True)
class CatalogImport:
    title: str
    author: str | None
    media_type: str
    format: str
    source_path: str
    original_name: str
    size_bytes: int
    checksum: str
    metadata: dict[str, object]


class CatalogReadPort(Protocol):
    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None: ...

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None: ...

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None: ...

    def get_volume(self, volume_id: uuid.UUID) -> CatalogVolume | None: ...

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]: ...

    def volumes_for_edition(self, edition_id: uuid.UUID) -> list[CatalogVolume]: ...


class CatalogImportPort(Protocol):
    def import_file(self, imported: CatalogImport) -> CatalogEdition: ...


class CatalogMetadataPort(Protocol):
    def apply_metadata(
        self, work_id: uuid.UUID, values: dict[str, object]
    ) -> CatalogWork | None: ...


@dataclass(frozen=True, slots=True)
class ShelfView:
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    kind: str
    rules: dict[str, object]
    pinned: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CategoryView:
    id: uuid.UUID
    kind: str
    name: str
    book_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SeriesView:
    name: str
    book_count: int
    latest_updated_at: datetime


class CatalogRepository(CatalogReadPort, CatalogImportPort, CatalogMetadataPort, Protocol):
    def list_works(
        self,
        *,
        offset: int,
        limit: int,
        query: str | None,
        media_type: str | None,
        status: str,
        series_name: str | None,
    ) -> tuple[list[CatalogWork], int]: ...

    def list_series(
        self, *, status: str, offset: int, limit: int
    ) -> tuple[list[SeriesView], int]: ...

    def add_work(
        self,
        *,
        title: str,
        author: str | None,
        media_type: str,
        metadata: dict[str, object],
    ) -> CatalogWork: ...

    def update_work(
        self,
        work_id: uuid.UUID,
        *,
        title: str | None,
        author: str | None,
        summary: str | None,
        status: str | None,
        metadata: dict[str, object] | None,
    ) -> CatalogWork | None: ...

    def list_editions(self, work_id: uuid.UUID) -> list[CatalogEdition]: ...

    def list_files(self, edition_id: uuid.UUID) -> list[CatalogFile]: ...

    def list_volumes(self, edition_id: uuid.UUID) -> list[CatalogVolume]: ...

    def update_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str | None,
        language: str | None,
        metadata: dict[str, object] | None,
    ) -> CatalogEdition | None: ...

    def set_primary_edition(self, work_id: uuid.UUID, edition_id: uuid.UUID) -> bool: ...

    def split_edition(
        self,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        *,
        title: str,
        author: str | None,
        copy_shelves: bool,
    ) -> uuid.UUID | None: ...

    def move_volume(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        direction: str,
    ) -> bool: ...

    def move_volume_to(
        self,
        work_id: uuid.UUID,
        volume_id: uuid.UUID,
        *,
        target_edition_id: uuid.UUID,
    ) -> bool: ...

    def list_shelves(self, owner_id: uuid.UUID) -> list[ShelfView]: ...

    def get_shelf(self, shelf_id: uuid.UUID, owner_id: uuid.UUID) -> ShelfView | None: ...

    def add_shelf(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        description: str | None,
        kind: str,
        rules: dict[str, object],
        pinned: bool,
    ) -> ShelfView: ...

    def update_shelf(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
        rules: dict[str, object] | None,
        pinned: bool | None,
    ) -> ShelfView | None: ...

    def delete_shelf(self, shelf_id: uuid.UUID, owner_id: uuid.UUID) -> bool: ...

    def add_shelf_item(
        self, shelf_id: uuid.UUID, owner_id: uuid.UUID, work_id: uuid.UUID
    ) -> bool: ...

    def remove_shelf_item(
        self, shelf_id: uuid.UUID, owner_id: uuid.UUID, work_id: uuid.UUID
    ) -> bool: ...

    def list_shelf_works(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[CatalogWork], list[uuid.UUID], int] | None: ...

    def replace_shelf_items(
        self,
        shelf_id: uuid.UUID,
        owner_id: uuid.UUID,
        work_ids: list[uuid.UUID],
    ) -> bool: ...

    def category_facets(self) -> dict[str, list[dict[str, object]]]: ...

    def list_categories(
        self,
        *,
        kind: str,
        query: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CategoryView], int]: ...

    def rename_category(self, category_id: uuid.UUID, name: str) -> CategoryView | None: ...

    def merge_categories(
        self,
        *,
        kind: str,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> CategoryView | None: ...

    def delete_category(self, category_id: uuid.UUID) -> bool: ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    catalog: CatalogRepository
