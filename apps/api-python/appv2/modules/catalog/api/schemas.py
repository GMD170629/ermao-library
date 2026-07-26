from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from appv2.modules.catalog.contracts import (
    BulkMutationResult,
    CatalogEdition,
    CatalogEditionDetail,
    CatalogFile,
    CatalogVolume,
    CatalogWork,
    DuplicateGroupView,
    FindReplacePreview,
    LibraryOperationView,
    ShelfView,
)
from appv2.platform.http import CamelModel


class WorkResponse(CamelModel):
    id: uuid.UUID
    title: str
    author: str | None
    media_type: str
    status: str
    cover_url: str | None
    summary: str | None
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, work: CatalogWork) -> WorkResponse:
        return cls(
            id=work.id,
            title=work.title,
            author=work.author,
            media_type=work.media_type,
            status=work.status,
            cover_url=(f"/api/v2/catalog/works/{work.id}/cover" if work.cover_key else None),
            summary=work.summary,
            metadata=work.metadata,
            created_at=work.created_at,
            updated_at=work.updated_at,
        )


class EditionResponse(CamelModel):
    id: uuid.UUID
    work_id: uuid.UUID
    title: str
    format: str
    language: str | None
    primary: bool
    metadata: dict[str, object]
    created_at: datetime

    @classmethod
    def from_view(cls, edition: CatalogEdition) -> EditionResponse:
        return cls.model_validate(edition)


class FileResponse(CamelModel):
    id: uuid.UUID
    edition_id: uuid.UUID
    volume_id: uuid.UUID | None
    original_name: str
    media_type: str
    size_bytes: int
    checksum: str
    sort_order: int
    duration_ms: int | None

    @classmethod
    def from_view(cls, file: CatalogFile) -> FileResponse:
        return cls.model_validate(file)


class VolumeResponse(CamelModel):
    id: uuid.UUID
    edition_id: uuid.UUID
    title: str
    sort_order: int
    page_count: int | None
    duration_ms: int | None

    @classmethod
    def from_view(cls, volume: CatalogVolume) -> VolumeResponse:
        return cls.model_validate(volume)


class EditionDetailResponse(EditionResponse):
    files: list[FileResponse]
    volumes: list[VolumeResponse]

    @classmethod
    def from_detail(cls, detail: CatalogEditionDetail) -> EditionDetailResponse:
        return cls(
            **EditionResponse.from_view(detail.edition).model_dump(),
            files=[FileResponse.from_view(file) for file in detail.files],
            volumes=[VolumeResponse.from_view(volume) for volume in detail.volumes],
        )


class WorkDetailResponse(WorkResponse):
    editions: list[EditionDetailResponse]


class CreateWorkRequest(CamelModel):
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    media_type: Literal["book", "comic", "pdf", "audiobook", "text"]
    metadata: dict[str, object] = Field(default_factory=dict)


class UpdateWorkRequest(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    summary: str | None = None
    status: Literal["active", "archived"] | None = None
    metadata: dict[str, object] | None = None


class UpdateEditionRequest(CamelModel):
    version_name: str | None = Field(default=None, min_length=1, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    published_at: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=20)
    isbn: str | None = Field(default=None, max_length=100)
    identifier: str | None = Field(default=None, max_length=500)
    narrator: str | None = Field(default=None, max_length=500)
    description: str | None = None

    def metadata_patch(self) -> dict[str, object]:
        values: dict[str, object | None] = {
            "publisher": self.publisher,
            "publishedAt": self.published_at,
            "isbn": self.isbn,
            "identifier": self.identifier,
            "narrator": self.narrator,
            "description": self.description,
        }
        return {key: value for key, value in values.items() if value is not None}


class SplitEditionRequest(CamelModel):
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    copy_shelves: bool = True


class SplitEditionResponse(CamelModel):
    new_work_id: uuid.UUID


class MoveVolumeRequest(CamelModel):
    direction: Literal["up", "down"]


class MoveVolumeToRequest(CamelModel):
    target_edition_id: uuid.UUID


class VolumeTransferResponse(CamelModel):
    transfer_mode: Literal[
        "MERGED_VOLUME",
        "ADDED_MEDIA",
        "ADDED_BACKUP_EDITION",
    ] = "MERGED_VOLUME"


class ShelfResponse(CamelModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    kind: str
    rules: dict[str, object]
    pinned: bool
    created_at: datetime

    @classmethod
    def from_view(cls, shelf: ShelfView) -> ShelfResponse:
        return cls.model_validate(shelf)


class ShelfRequest(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    kind: Literal["manual", "smart"] = "manual"
    rules: dict[str, object] = Field(default_factory=dict)
    pinned: bool = False
    book_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10_000)


class ShelfUpdateRequest(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    rules: dict[str, object] | None = None
    pinned: bool | None = None
    book_ids: list[uuid.UUID] | None = Field(default=None, max_length=10_000)


class BulkMetadataRequest(CamelModel):
    work_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=500)
    series_name: str | None = Field(default=None, max_length=500)
    add_tags: list[str] = Field(default_factory=list, max_length=200)
    remove_tags: list[str] = Field(default_factory=list, max_length=200)


FindReplaceField = Literal[
    "title",
    "author",
    "description",
    "seriesName",
    "tags",
    "publisher",
    "versionName",
    "language",
    "isbn",
    "identifier",
    "narrator",
]


class FindReplaceRequest(CamelModel):
    work_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    field: FindReplaceField
    find: str = Field(min_length=1, max_length=200)
    replacement: str = Field(max_length=2000)
    regex: bool = False
    case_sensitive: bool = False
    start_number: int = Field(default=1, ge=1, le=1_000_000)


class FindReplaceItemResponse(CamelModel):
    work_id: uuid.UUID
    title: str
    before: str | list[str]
    after: str | list[str]


class FindReplacePreviewResponse(CamelModel):
    changed_works: int
    changed_values: int
    items: list[FindReplaceItemResponse]

    @classmethod
    def from_view(cls, value: FindReplacePreview) -> FindReplacePreviewResponse:
        return cls(
            changed_works=value.changed_works,
            changed_values=value.changed_values,
            items=[FindReplaceItemResponse.model_validate(item) for item in value.items],
        )


class BulkSkippedResponse(CamelModel):
    work_id: uuid.UUID
    reason: str


class BulkMutationResponse(CamelModel):
    updated: int
    changed_values: int
    skipped: list[BulkSkippedResponse]

    @classmethod
    def from_view(cls, value: BulkMutationResult) -> BulkMutationResponse:
        return cls(
            updated=value.updated,
            changed_values=value.changed_values,
            skipped=[BulkSkippedResponse.model_validate(item) for item in value.skipped],
        )


class BulkShelfRequest(CamelModel):
    work_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    present: bool


class DuplicateWorkResponse(WorkResponse):
    pass


class DuplicateGroupResponse(CamelModel):
    id: uuid.UUID
    confidence: float
    reasons: list[str]
    works: list[DuplicateWorkResponse]

    @classmethod
    def from_view(cls, value: DuplicateGroupView) -> DuplicateGroupResponse:
        return cls(
            id=value.id,
            confidence=value.confidence,
            reasons=list(value.reasons),
            works=[
                DuplicateWorkResponse(**WorkResponse.from_view(work).model_dump())
                for work in value.works
            ],
        )


class DuplicateMergeRequest(CamelModel):
    target_work_id: uuid.UUID
    source_work_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class LibraryOperationResponse(CamelModel):
    id: uuid.UUID
    kind: str
    status: str
    affected_works: int
    undo_available: bool
    created_at: datetime

    @classmethod
    def from_view(cls, value: LibraryOperationView) -> LibraryOperationResponse:
        return cls.model_validate(value)
