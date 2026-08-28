"""Reader v4 resource-first HTTP contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi.responses import Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from typing_extensions import TypeAliasType

from app.contracts.http_errors import HttpContractError


class ReaderWireModel(BaseModel):
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


class ReadiumExtensionModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[str, ReaderJsonValue] = Field(init=False)


_MAX_UTC_EPOCH_MILLIS = 253_402_300_799_999
_MAX_LOCATOR_ENVELOPE_BYTES = 65_536


class ReadiumLocatorText(ReaderWireModel):
    before: str | None = Field(
        default=None, max_length=256, exclude_if=lambda value: value is None
    )
    highlight: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        exclude_if=lambda value: value is None,
    )
    after: str | None = Field(
        default=None, max_length=256, exclude_if=lambda value: value is None
    )


class ReadiumLocatorLocations(ReadiumExtensionModel):
    """Readium locations with validated portable anchors and extension fields."""

    css_selector: str | None = Field(
        default=None,
        alias="cssSelector",
        min_length=1,
        max_length=4096,
        exclude_if=lambda value: value is None,
    )
    fragments: list[str] = Field(default_factory=list, max_length=16)
    progression: float | None = Field(
        default=None, ge=0, le=1, exclude_if=lambda value: value is None
    )
    total_progression: float | None = Field(
        default=None,
        alias="totalProgression",
        ge=0,
        le=1,
        exclude_if=lambda value: value is None,
    )
    position: int | None = Field(
        default=None, ge=1, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_fragments(self) -> ReadiumLocatorLocations:
        if any(
            not fragment.strip() or len(fragment) > 4096 for fragment in self.fragments
        ):
            raise ValueError("Locator fragments must be non-empty and bounded")
        if self.css_selector is not None and not self.css_selector.strip():
            raise ValueError("Locator CSS selector must not be blank")
        return self


class ReadiumLocatorPayload(ReadiumExtensionModel):
    """Validated portable subset of a Readium Locator JSON object."""

    href: str = Field(min_length=1, max_length=8192)
    type: str = Field(min_length=1, max_length=256)
    title: str | None = Field(
        default=None, max_length=4096, exclude_if=lambda value: value is None
    )
    locations: ReadiumLocatorLocations
    text: ReadiumLocatorText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def require_exact_anchor(self) -> ReadiumLocatorPayload:
        if not self.href.strip() or not self.type.strip() or "\\" in self.href:
            raise ValueError("Readium Locator href and media type must be canonical")
        parsed_href = urlsplit(self.href)
        path_segments = parsed_href.path.replace("\\", "/").split("/")
        if (
            parsed_href.scheme
            or parsed_href.netloc
            or parsed_href.path.startswith("/")
            or ".." in path_segments
        ):
            raise ValueError("Readium Locator href must be publication-relative")
        has_text_anchor = (
            self.text is not None
            and self.text.highlight is not None
            and bool(self.text.highlight.strip())
        )
        if not (
            self.locations.css_selector or self.locations.fragments or has_text_anchor
        ):
            raise PydanticCustomError(
                "reader_locator_not_exact",
                "Readium Locator requires a CSS selector, fragment, or text highlight",
            )
        return self


class ReadiumEngineLocator(ReaderWireModel):
    engine: Literal["readium"]
    platform: Literal["android", "ios", "web"]
    version: str = Field(min_length=1, max_length=256)
    payload: ReadiumLocatorPayload

    @field_validator("version")
    @classmethod
    def require_non_blank_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Readium Navigator version must not be blank")
        return value


class OpaqueReadiumEngineLocator(ReaderWireModel):
    engine: Literal["readium"]
    platform: Literal["android", "ios", "web"]
    version: str = Field(min_length=1, max_length=256)
    payload: dict[str, ReaderJsonValue]

    @field_validator("version")
    @classmethod
    def require_non_blank_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Readium Navigator version must not be blank")
        return value


class ReflowableExactLocation(ReaderWireModel):
    kind: Literal["reflowable"]
    engine_locator: ReadiumEngineLocator = Field(alias="engineLocator")


class PdfExactLocation(ReaderWireModel):
    kind: Literal["pdf"]
    page_index: int = Field(alias="pageIndex", ge=0)
    page_progression: float = Field(alias="pageProgression", ge=0, le=1)
    engine_locator: OpaqueReadiumEngineLocator | None = Field(
        default=None, alias="engineLocator", exclude_if=lambda value: value is None
    )

    @field_validator("page_progression")
    @classmethod
    def require_canonical_page_progression(cls, value: float) -> float:
        if value != round(value * 10_000) / 10_000:
            raise ValueError("PDF page progression must be quantized to four decimals")
        return value


class ComicExactLocation(ReaderWireModel):
    kind: Literal["comic"]
    page_index: int = Field(alias="pageIndex", ge=0)
    resource_href: str = Field(alias="resourceHref", min_length=1, max_length=8192)
    engine_locator: OpaqueReadiumEngineLocator | None = Field(
        default=None, alias="engineLocator", exclude_if=lambda value: value is None
    )

    @field_validator("resource_href")
    @classmethod
    def require_canonical_resource_href(cls, value: str) -> str:
        _require_publication_relative_href(value)
        return value


class AudioExactLocation(ReaderWireModel):
    kind: Literal["audio"]
    asset_id: str = Field(alias="assetId", min_length=1, max_length=191)
    chapter_id: str | None = Field(
        default=None,
        alias="chapterId",
        min_length=1,
        max_length=191,
        exclude_if=lambda value: value is None,
    )
    position_millis: int = Field(alias="positionMillis", ge=0)
    engine_locator: OpaqueReadiumEngineLocator | None = Field(
        default=None, alias="engineLocator", exclude_if=lambda value: value is None
    )

    @field_validator("asset_id", "chapter_id")
    @classmethod
    def require_non_blank_identity(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Audio location identities must not be blank")
        return value


ExactReaderLocation: TypeAlias = Annotated[
    ReflowableExactLocation
    | PdfExactLocation
    | ComicExactLocation
    | AudioExactLocation,
    Field(discriminator="kind"),
]


def _require_publication_relative_href(value: str) -> None:
    if not value.strip() or "\\" in value:
        raise ValueError("Publication resource href must be canonical")
    parsed_href = urlsplit(value)
    if (
        parsed_href.scheme
        or parsed_href.netloc
        or parsed_href.path.startswith("/")
        or ".." in parsed_href.path.replace("\\", "/").split("/")
    ):
        raise ValueError("Publication resource href must be publication-relative")


def _require_bounded_exact_location(location: ExactReaderLocation) -> None:
    encoded = json.dumps(
        location.model_dump(by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_LOCATOR_ENVELOPE_BYTES:
        raise ValueError("Exact Reader location exceeds 64 KiB")


class ReaderProgressPut(ReaderWireModel):
    schema_version: Literal[4] = Field(alias="schemaVersion")
    client_id: str = Field(alias="clientId", min_length=1, max_length=256)
    mutation_id: UUID = Field(alias="mutationId")
    base_revision: int = Field(alias="baseRevision", ge=0)
    captured_at_epoch_millis: int = Field(
        alias="capturedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    locator: ExactReaderLocation

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_location_fields(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        request = cast(Mapping[object, object], value)
        raw_locator = request.get("locator")
        if not isinstance(raw_locator, Mapping):
            return value
        locator = cast(Mapping[object, object], raw_locator)
        for optional_field in ("engineLocator", "chapterId"):
            if optional_field in locator and locator[optional_field] is None:
                raise ValueError(
                    f"Reader location {optional_field} must be omitted instead of null"
                )
        return value

    @field_validator("client_id")
    @classmethod
    def require_non_blank_client_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reader clientId must not be blank")
        return value

    @model_validator(mode="after")
    def require_bounded_locator(self) -> ReaderProgressPut:
        _require_bounded_exact_location(self.locator)
        return self


# Bookmarks retain their independent collection contract until their revisioned
# synchronization capability is replaced. They deliberately do not participate
# in progress restoration.
class ReflowLocation(ReaderWireModel):
    kind: Literal["reflow"]
    resource_key: str = Field(alias="resourceKey", min_length=1, max_length=2048)
    progression: float | None = Field(default=None, ge=0, le=1)


class ComicLocation(ReaderWireModel):
    kind: Literal["comic"]
    page_index: int = Field(alias="pageIndex", ge=1)


class PdfLocation(ReaderWireModel):
    kind: Literal["pdf"]
    page_number: int = Field(alias="pageNumber", ge=1)


class AudioLocation(ReaderWireModel):
    kind: Literal["audio"]
    asset_id: str = Field(alias="assetId", min_length=1, max_length=191)
    chapter_id: str | None = Field(default=None, alias="chapterId", max_length=191)
    position_ms: int = Field(alias="positionMs", ge=0)


ReaderLocation: TypeAlias = Annotated[
    ReflowLocation | ComicLocation | PdfLocation | AudioLocation,
    Field(discriminator="kind"),
]


class ReaderBookSummary(ReaderWireModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")


class ReaderResourceSummary(ReaderWireModel):
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


class ReaderNavigationUnitSummary(ReaderWireModel):
    id: str
    index: int
    title: str
    href: str | None = None
    asset_id: str | None = Field(default=None, alias="assetId")
    start_ms: int | None = Field(default=None, alias="startMs", ge=0)
    end_ms: int | None = Field(default=None, alias="endMs", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)
    metadata: dict[str, ReaderJsonValue] = Field(default_factory=dict)


class ReaderAssetSummary(ReaderWireModel):
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


class ReaderPublicationAccess(ReaderWireModel):
    kind: Literal["reflowable", "comic"]
    manifest_url: str = Field(alias="manifestUrl")
    positions_url: str | None = Field(default=None, alias="positionsUrl")
    page_url_template: str | None = Field(default=None, alias="pageUrlTemplate")
    image_variants: list[Literal["original", "data-saver"]] = Field(
        default_factory=list,
        alias="imageVariants",
    )

    @model_validator(mode="after")
    def validate_kind(self) -> ReaderPublicationAccess:
        if self.kind == "reflowable":
            if self.positions_url is None or self.page_url_template is not None:
                raise ValueError("Invalid reflowable publication access")
            if self.image_variants:
                raise ValueError("Invalid reflowable publication access")
        elif (
            self.positions_url is not None
            or self.page_url_template is None
            or self.image_variants != ["original", "data-saver"]
        ):
            raise ValueError("Invalid comic publication access")
        return self


class ReaderComicManifestPage(ReaderWireModel):
    page_index: int = Field(alias="pageIndex", ge=0)
    resource_href: str = Field(alias="resourceHref", min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=191)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, alias="sizeBytes", ge=0)


class ReaderComicManifestData(ReaderWireModel):
    schema_version: Literal[1] = Field(1, alias="schemaVersion")
    kind: Literal["comic"] = "comic"
    resource_id: str = Field(alias="resourceId", min_length=1)
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


class ReaderComicManifestResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderComicManifestData


class ReaderProgressSnapshot(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    revision: int = Field(ge=1)
    client_id: str = Field(alias="clientId", min_length=1, max_length=256)
    locator: ExactReaderLocation
    display_percent: float = Field(alias="displayPercent", ge=0, le=100)
    received_at_epoch_millis: int = Field(
        alias="receivedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    captured_at_epoch_millis: int | None = Field(
        default=None,
        alias="capturedAtEpochMillis",
        ge=0,
        le=_MAX_UTC_EPOCH_MILLIS,
        exclude_if=lambda value: value is None,
    )


class ReaderBootstrapData(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    user_id: str = Field(alias="userId")
    reader_type: ReaderFormat = Field(alias="readerType")
    source_format: ReaderSourceFormat = Field(alias="sourceFormat")
    book: ReaderBookSummary
    resource: ReaderResourceSummary
    available_resources: list[ReaderResourceSummary] = Field(alias="availableResources")
    assets: list[ReaderAssetSummary] = Field(alias="assets")
    units: list[ReaderNavigationUnitSummary]
    resource_url: str = Field(alias="resourceUrl")
    capabilities: ReaderCapabilities
    publication: ReaderPublicationAccess | None = None
    progress_snapshot: ReaderProgressSnapshot | None = Field(
        default=None, alias="progressSnapshot"
    )


class ReaderBootstrapResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderBootstrapData


class ReaderProgressResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderProgressSnapshot


class ReaderProgressStateData(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    progress_snapshot: ReaderProgressSnapshot | None = Field(alias="progressSnapshot")


class ReaderProgressStateResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderProgressStateData


class ReaderReadingStatusPut(ReaderWireModel):
    status: Literal["UNREAD", "FINISHED"]


class ReaderReadingStatusData(ReaderWireModel):
    resource_id: str = Field(alias="resourceId")
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
    bookmarks: list[ReaderBookmark] = Field(max_length=500)

    @model_validator(mode="after")
    def require_unique_bookmark_ids(self) -> ReaderBookmarksReplaceRequest:
        bookmark_ids = [bookmark.id for bookmark in self.bookmarks]
        if len(bookmark_ids) != len(set(bookmark_ids)):
            raise ValueError("Bookmark IDs must be unique within a resource")
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


class ReaderProgressConflictBody(ReaderWireModel):
    message: str
    code: Literal["READER_PROGRESS_CONFLICT"] = "READER_PROGRESS_CONFLICT"
    current: ReaderProgressSnapshot


class ReaderUnauthorizedError(HttpContractError[ReaderErrorBody]):
    status_code = 401
    body_model = ReaderErrorBody


class ReaderNotFoundError(HttpContractError[ReaderErrorBody]):
    status_code = 404
    body_model = ReaderErrorBody


class ReaderConflictError(HttpContractError[ReaderErrorBody]):
    status_code = 409
    body_model = ReaderErrorBody


class ReaderProgressConflictError(HttpContractError[ReaderProgressConflictBody]):
    status_code = 409
    body_model = ReaderProgressConflictBody


class ReaderValidationError(HttpContractError[ReaderErrorBody]):
    status_code = 422
    body_model = ReaderErrorBody
