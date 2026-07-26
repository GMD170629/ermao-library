from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol

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
    file_media_type: str
    format: str
    source_path: str
    original_name: str
    size_bytes: int
    checksum: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class PreparedCatalogFile:
    source_path: str
    original_name: str
    media_type: str
    size_bytes: int
    checksum: str
    sort_order: int = 0
    volume_key: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedCatalogVolume:
    key: str
    title: str
    sort_order: int
    page_count: int | None = None
    duration_ms: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedPublication:
    identity_key: str
    title: str
    author: str | None
    media_type: str
    format: str
    language: str | None
    identifiers: tuple[str, ...]
    metadata: dict[str, object]
    volumes: tuple[PreparedCatalogVolume, ...]
    files: tuple[PreparedCatalogFile, ...]
    cover_content: bytes | None = None
    cover_media_type: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogImportResult:
    work_id: uuid.UUID
    edition_id: uuid.UUID
    volume_ids: tuple[uuid.UUID, ...]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class CatalogDeletion:
    work_id: uuid.UUID
    cover_key: str | None
    storage_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverResource:
    path: Path
    media_type: str
    etag: str
    last_modified: datetime


class CoverStoragePort(Protocol):
    def store(self, work_id: uuid.UUID, stream: BinaryIO) -> str: ...

    def store_many(
        self,
        work_ids: list[uuid.UUID],
        stream: BinaryIO,
    ) -> dict[uuid.UUID, str]: ...

    def open(self, key: str, size: str) -> CoverResource: ...

    def delete(self, key: str) -> None: ...


class CatalogFileStoragePort(Protocol):
    def delete(self, paths: tuple[str, ...], *, include_sources: bool) -> None: ...


class CatalogReadPort(Protocol):
    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None: ...

    def get_edition(self, edition_id: uuid.UUID) -> CatalogEdition | None: ...

    def editions_for_work(self, work_id: uuid.UUID) -> list[CatalogEdition]: ...

    def get_file(self, file_id: uuid.UUID) -> CatalogFile | None: ...

    def get_volume(self, volume_id: uuid.UUID) -> CatalogVolume | None: ...

    def files_for_edition(self, edition_id: uuid.UUID) -> list[CatalogFile]: ...

    def volumes_for_edition(self, edition_id: uuid.UUID) -> list[CatalogVolume]: ...


class CatalogOrganizationReadPort(Protocol):
    def get_work(self, work_id: uuid.UUID) -> CatalogWork | None: ...

    def list_active_works(self, *, offset: int, limit: int) -> list[CatalogWork]: ...


class CatalogImportPort(Protocol):
    def import_publication(self, publication: PreparedPublication) -> CatalogImportResult: ...

    def import_file(self, imported: CatalogImport) -> CatalogEdition: ...

    def publish_conversion(
        self,
        source_edition_id: uuid.UUID,
        converted: CatalogImport,
    ) -> CatalogEdition | None: ...


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


@dataclass(frozen=True, slots=True)
class BulkSkipped:
    work_id: uuid.UUID
    reason: str


@dataclass(frozen=True, slots=True)
class BulkMutationResult:
    updated: int
    changed_values: int
    skipped: tuple[BulkSkipped, ...] = ()


@dataclass(frozen=True, slots=True)
class FindReplaceItem:
    work_id: uuid.UUID
    title: str
    before: str | list[str]
    after: str | list[str]


@dataclass(frozen=True, slots=True)
class FindReplacePreview:
    changed_works: int
    changed_values: int
    items: tuple[FindReplaceItem, ...]


@dataclass(frozen=True, slots=True)
class DuplicateGroupView:
    id: uuid.UUID
    confidence: float
    reasons: tuple[str, ...]
    works: tuple[CatalogWork, ...]


@dataclass(frozen=True, slots=True)
class LibraryOperationView:
    id: uuid.UUID
    kind: str
    status: str
    affected_works: int
    undo_available: bool
    created_at: datetime


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
        sort: str,
        sort_direction: str,
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

    def delete_work(self, work_id: uuid.UUID) -> CatalogDeletion | None: ...

    def set_cover_key(self, work_id: uuid.UUID, cover_key: str) -> CatalogWork | None: ...

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

    def list_duplicate_groups(self, *, limit: int) -> list[DuplicateGroupView]: ...

    def publish_conversion(
        self,
        source_edition_id: uuid.UUID,
        converted: CatalogImport,
    ) -> CatalogEdition | None: ...

    def merge_duplicate_works(
        self,
        *,
        actor_id: uuid.UUID,
        target_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> LibraryOperationView | None: ...

    def undo_library_operation(
        self,
        *,
        actor_id: uuid.UUID,
        operation_id: uuid.UUID,
    ) -> LibraryOperationView | None: ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    catalog: CatalogRepository
