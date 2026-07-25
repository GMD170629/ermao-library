from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from appv2.modules.catalog.contracts import (
    CatalogEdition,
    CatalogEditionDetail,
    CatalogFile,
    CatalogVolume,
    CatalogWork,
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
