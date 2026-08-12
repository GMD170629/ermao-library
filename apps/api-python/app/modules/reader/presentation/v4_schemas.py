"""Reader v4 volume-first HTTP contracts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeAliasType

from app.contracts.http_errors import HttpContractError


class ReaderWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


ReaderFormat = Literal["reflowable", "comic", "pdf", "audio"]
ReflowableFormat = Literal["epub", "mobi", "azw", "azw3", "prc", "fb2", "txt"]
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
_MAX_UTC_EPOCH_MILLIS = 253_402_300_799_999


class ReaderContentFingerprint(ReaderWireModel):
    original_file_hash: str = Field(
        alias="originalFileHash", min_length=1, max_length=191
    )
    parser_version: str = Field(alias="parserVersion", min_length=1, max_length=191)
    normalization_version: str = Field(
        alias="normalizationVersion", min_length=1, max_length=191
    )


class ReaderTextQuote(ReaderWireModel):
    exact: str = Field(min_length=1, max_length=8192)
    prefix: str | None = Field(default=None, max_length=4096)
    suffix: str | None = Field(default=None, max_length=4096)


class ReaderEngineLocator(ReaderWireModel):
    engine: Literal["readium", "foliate"]
    platform: Literal["android", "ios", "web"]
    version: str = Field(min_length=1, max_length=191)
    payload: dict[str, ReaderJsonValue]

    @model_validator(mode="after")
    def require_bounded_payload(self) -> ReaderEngineLocator:
        encoded = json.dumps(
            self.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > 65_536:
            raise ValueError("engineLocator payload exceeds 64 KiB")
        return self


class ReflowLocation(ReaderWireModel):
    kind: Literal["reflow"]
    resource_key: str | None = Field(
        default=None, alias="resourceKey", min_length=1, max_length=2048
    )
    progression: float | None = Field(default=None, ge=0, le=1)
    position: int | None = Field(default=None, ge=1)
    text_quote: ReaderTextQuote | None = Field(default=None, alias="textQuote")
    content_fingerprint: ReaderContentFingerprint | None = Field(
        default=None, alias="contentFingerprint"
    )
    engine_locator: ReaderEngineLocator | None = Field(
        default=None, alias="engineLocator"
    )

    @model_validator(mode="after")
    def require_anchor(self) -> ReflowLocation:
        if all(
            value is None
            for value in (
                self.resource_key,
                self.progression,
                self.position,
                self.text_quote,
                self.engine_locator,
            )
        ):
            raise ValueError("Reflow location requires an anchor")
        return self


class ComicLocation(ReaderWireModel):
    kind: Literal["comic"]
    page_index: int = Field(alias="pageIndex", ge=1)
    engine_locator: ReaderEngineLocator | None = Field(
        default=None, alias="engineLocator"
    )


class PdfLocation(ReaderWireModel):
    kind: Literal["pdf"]
    page_number: int = Field(alias="pageNumber", ge=1)
    engine_locator: ReaderEngineLocator | None = Field(
        default=None, alias="engineLocator"
    )


class AudioLocation(ReaderWireModel):
    kind: Literal["audio"]
    file_id: str = Field(alias="fileId", min_length=1, max_length=191)
    chapter_id: str | None = Field(default=None, alias="chapterId", max_length=191)
    position_ms: int = Field(alias="positionMs", ge=0)
    engine_locator: ReaderEngineLocator | None = Field(
        default=None, alias="engineLocator"
    )


ReaderLocation: TypeAlias = Annotated[
    ReflowLocation | ComicLocation | PdfLocation | AudioLocation,
    Field(discriminator="kind"),
]


class ReaderProgressPut(ReaderWireModel):
    schema_version: Literal[4] = Field(alias="schemaVersion")
    client_id: str = Field(alias="clientId", min_length=1, max_length=191)
    updated_at_epoch_millis: int = Field(
        alias="updatedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    percent: float = Field(ge=0, le=100)
    location: ReaderLocation | None = None
    content_fingerprint: str = Field(
        alias="contentFingerprint", min_length=1, max_length=191
    )


class ReaderBookSummary(ReaderWireModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")


class ReaderMediaVersionSummary(ReaderWireModel):
    id: str
    work_id: str = Field(alias="workId")
    media_kind: Literal["EBOOK", "COMIC", "AUDIOBOOK"] = Field(alias="mediaKind")
    completed: bool


class ReaderVolumeSummary(ReaderWireModel):
    id: str
    media_version_id: str = Field(alias="mediaVersionId")
    title: str
    volume_index: float | None = Field(default=None, alias="volumeIndex")
    sort_order: int = Field(alias="sortOrder")
    format: str
    reader_type: ReaderFormat = Field(alias="readerType")
    derived_from_volume_id: str | None = Field(
        default=None, alias="derivedFromVolumeId"
    )
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    track_count: int | None = Field(default=None, alias="trackCount")
    progress: float = Field(ge=0, le=100)
    last_read_at: datetime | None = Field(default=None, alias="lastReadAt")


class ReaderUnitSummary(ReaderWireModel):
    id: str
    index: int
    title: str
    href: str | None = None
    file_id: str | None = Field(default=None, alias="fileId")
    start_ms: int | None = Field(default=None, alias="startMs", ge=0)
    end_ms: int | None = Field(default=None, alias="endMs", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)
    metadata: dict[str, ReaderJsonValue] = Field(default_factory=dict)


class ReaderFileSummary(ReaderWireModel):
    id: str
    kind: str
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    sort_order: int = Field(alias="sortOrder")
    url: str
    codec: str | None = None
    content_hash: str | None = Field(default=None, alias="contentHash")


class ReaderCapabilities(ReaderWireModel):
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


class ReaderProgressSnapshot(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    client_id: str = Field(alias="clientId")
    updated_at_epoch_millis: int = Field(
        alias="updatedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    percent: float = Field(ge=0, le=100)
    location: ReaderLocation | None = None
    content_fingerprint: str = Field(alias="contentFingerprint")


class ReaderBootstrapData(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    user_id: str = Field(alias="userId")
    reader_type: ReaderFormat = Field(alias="readerType")
    source_format: ReflowableFormat | None = Field(default=None, alias="sourceFormat")
    content_fingerprint: str = Field(alias="contentFingerprint")
    book: ReaderBookSummary
    media_version: ReaderMediaVersionSummary = Field(alias="mediaVersion")
    volume: ReaderVolumeSummary
    available_volumes: list[ReaderVolumeSummary] = Field(alias="availableVolumes")
    files: list[ReaderFileSummary]
    units: list[ReaderUnitSummary]
    file_url: str = Field(alias="fileUrl")
    capabilities: ReaderCapabilities
    progress_snapshot: ReaderProgressSnapshot | None = Field(
        default=None, alias="progressSnapshot"
    )


class ReaderBootstrapResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderBootstrapData


class ReaderProgressData(ReaderWireModel):
    progress: ReaderProgressSnapshot


class ReaderProgressResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderProgressData


class ReaderReadingStatusPut(ReaderWireModel):
    status: Literal["UNREAD", "FINISHED"]


class ReaderReadingStatusData(ReaderWireModel):
    volume_id: str = Field(alias="volumeId")
    status: Literal["UNREAD", "FINISHED"]
    percent: float = Field(ge=0, le=100)


class ReaderReadingStatusResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderReadingStatusData


class ReaderBookmark(ReaderWireModel):
    id: str = Field(min_length=1, max_length=5000)
    location: ReaderLocation
    label: str = Field(max_length=500)
    percent: float = Field(ge=0, le=100)
    created_at: datetime = Field(alias="createdAt")


class ReaderBookmarksReplaceRequest(ReaderWireModel):
    content_fingerprint: str = Field(
        alias="contentFingerprint", min_length=1, max_length=191
    )
    bookmarks: list[ReaderBookmark] = Field(max_length=500)

    @model_validator(mode="after")
    def require_unique_bookmark_ids(self) -> ReaderBookmarksReplaceRequest:
        bookmark_ids = [bookmark.id for bookmark in self.bookmarks]
        if len(bookmark_ids) != len(set(bookmark_ids)):
            raise ValueError("Bookmark IDs must be unique within a volume")
        return self


class ReaderBookmarksData(ReaderWireModel):
    bookmarks: list[ReaderBookmark]


class ReaderBookmarksResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderBookmarksData


class ReaderErrorBody(ReaderWireModel):
    message: str
    code: str | None = None
    details: dict[str, ReaderJsonValue] | None = None


class ReaderUnauthorizedError(HttpContractError[ReaderErrorBody]):
    status_code = 401
    body_model = ReaderErrorBody


class ReaderNotFoundError(HttpContractError[ReaderErrorBody]):
    status_code = 404
    body_model = ReaderErrorBody


class ReaderConflictError(HttpContractError[ReaderErrorBody]):
    status_code = 409
    body_model = ReaderErrorBody


class ReaderValidationError(HttpContractError[ReaderErrorBody]):
    status_code = 422
    body_model = ReaderErrorBody
