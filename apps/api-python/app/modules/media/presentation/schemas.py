from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi.responses import FileResponse, Response
from pydantic import Field

from app.contracts.http import HttpContractModel


class MediaFileResponse(Response):
    media_type = "application/octet-stream"


class MediaImageResponse(Response):
    media_type = "image/jpeg"


class MediaArchiveResponse(FileResponse):
    media_type = "application/zip"


class VolumeArchiveRequest(HttpContractModel):
    volume_ids: list[str] = Field(alias="volumeIds", min_length=1)


class VolumePage(HttpContractModel):
    id: str
    volume_id: str = Field(alias="volumeId")
    file_id: str | None = Field(default=None, alias="fileId")
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


class VolumePagesPayload(HttpContractModel):
    pages: list[VolumePage]
    total: int = Field(ge=0)


class VolumePagesResponse(HttpContractModel):
    ok: Literal[True] = True
    data: VolumePagesPayload
