"""Version-neutral Reader wire models shared by v4 tombstone-era code and v5.

These models describe catalog/publication metadata only.  Progress and Locator
contracts live in their versioned modules and must not be imported here.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypeAlias

from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeAliasType


class ReaderCommonWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReaderComicPageResponse(Response):
    media_type = "application/octet-stream"


ReaderFormat = Literal["reflowable", "comic", "pdf", "audio"]
ReaderSourceFormat = Literal[
    "epub",
    "mobi",
    "azw",
    "azw3",
    "prc",
    "txt",
    "fb2",
    "cbz",
    "zip",
    "cbr",
    "rar",
    "image_dir",
    "pdf",
    "audio",
    "audiobook",
    "audiobook_dir",
    "m4b",
    "m4a",
    "mp3",
]
if TYPE_CHECKING:
    ReaderJsonValue: TypeAlias = (
        str
        | int
        | float
        | bool
        | None
        | list["ReaderJsonValue"]
        | dict[str, "ReaderJsonValue"]
    )
else:
    ReaderJsonValue = TypeAliasType(
        "ReaderJsonValue",
        str
        | int
        | float
        | bool
        | None
        | list["ReaderJsonValue"]
        | dict[str, "ReaderJsonValue"],
    )


class ReaderBookSummary(ReaderCommonWireModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")


class ReaderResourceSummary(ReaderCommonWireModel):
    id: str
    book_id: str = Field(alias="bookId")
    source_node_id: str = Field(alias="sourceNodeId")
    title: str
    resource_index: float | None = Field(default=None, alias="resourceIndex")
    sort_order: int = Field(alias="sortOrder")
    format: str
    reader_type: ReaderFormat = Field(alias="readerType")
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    track_count: int | None = Field(default=None, alias="trackCount")
    progress: float = Field(ge=0, le=100)
    resource_completed: bool = Field(alias="resourceCompleted")
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")


class ReaderNavigationUnitSummary(ReaderCommonWireModel):
    id: str
    index: int
    title: str
    href: str | None = None
    asset_id: str | None = Field(default=None, alias="assetId")
    start_ms: int | None = Field(default=None, alias="startMs", ge=0)
    end_ms: int | None = Field(default=None, alias="endMs", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)
    metadata: dict[str, ReaderJsonValue] = Field(default_factory=dict)


class ReaderAssetSummary(ReaderCommonWireModel):
    id: str
    title: str
    resource_id: str = Field(alias="resourceId")
    source_node_id: str = Field(alias="sourceNodeId")
    role: str
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    sort_order: int = Field(alias="sortOrder")
    url: str
    codec: str | None = None


class ReaderCapabilities(ReaderCommonWireModel):
    can_go_next: bool = Field(alias="canGoNext")
    can_go_previous: bool = Field(alias="canGoPrevious")
    can_jump_to_progress: bool = Field(alias="canJumpToProgress")
    can_jump_to_href: bool = Field(alias="canJumpToHref")
    can_jump_to_index: bool = Field(alias="canJumpToIndex")
    can_zoom: bool = Field(alias="canZoom")
    can_select_text: bool = Field(alias="canSelectText")
    supports_pagination: bool = Field(alias="supportsPagination")
    supports_scrolling: bool = Field(alias="supportsScrolling")
    supports_spreads: bool = Field(alias="supportsSpreads")


class ReaderPublicationAccess(ReaderCommonWireModel):
    kind: Literal["comic"]
    manifest_url: str = Field(alias="manifestUrl")
    positions_url: str | None = Field(default=None, alias="positionsUrl")
    page_url_template: str | None = Field(default=None, alias="pageUrlTemplate")
    image_variants: list[Literal["original", "data-saver"]] = Field(
        default_factory=list,
        alias="imageVariants",
    )

    @model_validator(mode="after")
    def validate_kind(self) -> ReaderPublicationAccess:
        if (
            self.positions_url is not None
            or self.page_url_template is None
            or self.image_variants != ["original", "data-saver"]
        ):
            raise ValueError("Invalid comic publication access")
        return self


class ReaderComicManifestPage(ReaderCommonWireModel):
    page_index: int = Field(alias="pageIndex", ge=0)
    resource_href: str = Field(alias="resourceHref", min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=191)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, alias="sizeBytes", ge=0)


class ReaderComicManifestData(ReaderCommonWireModel):
    schema_version: Literal[2] = Field(2, alias="schemaVersion")
    kind: Literal["comic"] = "comic"
    resource_id: str = Field(alias="resourceId", min_length=1)
    revision: str = Field(min_length=71, max_length=71)
    source_format: Literal["cbz", "zip", "cbr", "rar", "image_dir"] = Field(
        alias="sourceFormat"
    )
    page_count: int = Field(alias="pageCount", gt=0)
    reading_order: list[ReaderComicManifestPage] = Field(alias="readingOrder")

    @model_validator(mode="after")
    def validate_reading_order(self) -> ReaderComicManifestData:
        if len(self.reading_order) != self.page_count:
            raise ValueError("Comic page count does not match reading order")
        if [page.page_index for page in self.reading_order] != list(
            range(self.page_count)
        ):
            raise ValueError("Comic reading order must be zero-based and contiguous")
        if any(
            page.resource_href != f"pages/{page.page_index}"
            for page in self.reading_order
        ):
            raise ValueError("Comic resource href is not canonical")
        return self


class ReaderComicManifestResponse(ReaderCommonWireModel):
    ok: Literal[True] = True
    data: ReaderComicManifestData


class ReaderReadingStatusPut(ReaderCommonWireModel):
    status: Literal["UNREAD", "FINISHED"]


class ReaderReadingStatusData(ReaderCommonWireModel):
    resource_id: str = Field(alias="resourceId")
    status: Literal["UNREAD", "FINISHED"]
    percent: float = Field(ge=0, le=100)


class ReaderReadingStatusResponse(ReaderCommonWireModel):
    ok: Literal[True] = True
    data: ReaderReadingStatusData


__all__ = [
    "ReaderAssetSummary",
    "ReaderBookSummary",
    "ReaderCapabilities",
    "ReaderComicManifestData",
    "ReaderComicManifestPage",
    "ReaderComicManifestResponse",
    "ReaderComicPageResponse",
    "ReaderFormat",
    "ReaderJsonValue",
    "ReaderNavigationUnitSummary",
    "ReaderPublicationAccess",
    "ReaderReadingStatusData",
    "ReaderReadingStatusPut",
    "ReaderReadingStatusResponse",
    "ReaderResourceSummary",
    "ReaderSourceFormat",
]
