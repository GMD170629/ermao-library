"""Reader v4 volume-first HTTP contracts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, TypeAlias
from urllib.parse import urlsplit
from uuid import UUID

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


class ReadiumExtensionModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[str, ReaderJsonValue] = Field(init=False)


_MAX_UTC_EPOCH_MILLIS = 253_402_300_799_999
_MAX_LOCATOR_ENVELOPE_BYTES = 65_536
_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[a-fA-F0-9]{64}$")


class PublicationFingerprint(ReaderWireModel):
    original_file_hash: str = Field(alias="originalFileHash", max_length=71)
    parser: str = Field(min_length=1, max_length=256)
    normalization: str = Field(min_length=1, max_length=256)

    @field_validator("parser", "normalization")
    @classmethod
    def require_non_blank_component(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Publication fingerprint components must not be blank")
        return value

    @field_validator("original_file_hash")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("originalFileHash must contain a SHA-256 digest")
        return f"sha256:{value.removeprefix('sha256:').lower()}"


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


class LocatorEnvelope(ReaderWireModel):
    engine: Literal["readium"]
    platform: Literal["android", "ios", "web"]
    version: str = Field(min_length=1, max_length=256)
    publication: PublicationFingerprint
    payload: ReadiumLocatorPayload

    @field_validator("version")
    @classmethod
    def require_non_blank_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Readium Navigator version must not be blank")
        return value

    @model_validator(mode="after")
    def require_bounded_envelope(self) -> LocatorEnvelope:
        encoded = json.dumps(
            self.model_dump(by_alias=True, exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_LOCATOR_ENVELOPE_BYTES:
            raise ValueError("Locator envelope exceeds 64 KiB")
        return self


class ReaderProgressPut(ReaderWireModel):
    schema_version: Literal[4] = Field(alias="schemaVersion")
    client_id: str = Field(alias="clientId", min_length=1, max_length=256)
    mutation_id: UUID = Field(alias="mutationId")
    base_revision: int = Field(alias="baseRevision", ge=0)
    captured_at_epoch_millis: int = Field(
        alias="capturedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    locator: LocatorEnvelope

    @field_validator("client_id")
    @classmethod
    def require_non_blank_client_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reader clientId must not be blank")
        return value


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
    file_id: str = Field(alias="fileId", min_length=1, max_length=191)
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


class ReaderPublicationAccess(ReaderWireModel):
    manifest_url: str = Field(alias="manifestUrl")
    positions_url: str = Field(alias="positionsUrl")


class ReaderProgressSnapshot(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    revision: int = Field(ge=1)
    locator: LocatorEnvelope
    display_percent: float = Field(alias="displayPercent", ge=0, le=100)
    received_at_epoch_millis: int = Field(
        alias="receivedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )
    captured_at_epoch_millis: int | None = Field(
        default=None, alias="capturedAtEpochMillis", ge=0, le=_MAX_UTC_EPOCH_MILLIS
    )


class ReaderBootstrapData(ReaderWireModel):
    schema_version: Literal[4] = Field(4, alias="schemaVersion")
    user_id: str = Field(alias="userId")
    reader_type: ReaderFormat = Field(alias="readerType")
    source_format: ReflowableFormat | None = Field(default=None, alias="sourceFormat")
    publication_fingerprint: PublicationFingerprint = Field(
        alias="publicationFingerprint"
    )
    book: ReaderBookSummary
    media_version: ReaderMediaVersionSummary = Field(alias="mediaVersion")
    volume: ReaderVolumeSummary
    available_volumes: list[ReaderVolumeSummary] = Field(alias="availableVolumes")
    files: list[ReaderFileSummary]
    units: list[ReaderUnitSummary]
    file_url: str = Field(alias="fileUrl")
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
