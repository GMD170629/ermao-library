from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi.responses import Response
from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


class MediaAssetResponse(Response):
    media_type = "application/octet-stream"


class MediaImageResponse(Response):
    media_type = "image/jpeg"


class ResourcePage(HttpContractModel):
    id: str
    resource_id: str = Field(alias="resourceId")
    asset_id: str | None = Field(default=None, alias="assetId")
    unit_type: str = Field(alias="unitType")
    title: str | None = None
    href: str | None = None
    media_type: str | None = Field(default=None, alias="mediaType")
    sort_order: int = Field(alias="sortOrder")
    width: int | None = None
    height: int | None = None
    size: int | None = None
    metadata_json: str | None = Field(default=None, alias="metadataJson")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class ResourcePagesPayload(HttpContractModel):
    pages: list[ResourcePage]
    total: int = Field(ge=0)
    revision: str = Field(min_length=71, max_length=71)


class ResourcePagesResponse(HttpContractModel):
    ok: Literal[True] = True
    data: ResourcePagesPayload


class ResourceDownloadPayload(HttpContractModel):
    supported: Literal[False] = False
    message: str


class ResourceDownloadResponse(SuccessEnvelope[ResourceDownloadPayload]):
    pass
