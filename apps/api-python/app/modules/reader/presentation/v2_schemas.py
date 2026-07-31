from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.http_errors import HttpContractError


class ReaderWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


ReaderFormat = Literal["epub", "comic", "pdf", "audio"]
ReaderTheme = Literal["day", "warm", "night", "black"]


class AppearancePreferences(ReaderWireModel):
    theme: ReaderTheme = "warm"


class EpubPreferences(ReaderWireModel):
    font_size: int = Field(18, alias="fontSize", ge=14, le=30)
    line_height: float = Field(1.9, alias="lineHeight", ge=1.4, le=2.4)
    page_width: int = Field(1350, alias="pageWidth", ge=600, le=1350)
    font_family: Literal["pingfang", "heiti", "songti", "yahei", "kaiti"] = Field("pingfang", alias="fontFamily")
    spread_mode: Literal["single", "double"] = Field("single", alias="spreadMode")
    page_turn_animation: Literal["slide", "off"] = Field("slide", alias="pageTurnAnimation")
    flow: Literal["paginated", "scrolled"] = "paginated"

    @field_validator("page_turn_animation", mode="before")
    @classmethod
    def migrate_kindle_animation(cls, value: object) -> object:
        return "slide" if value == "kindle" else value


class ComicPreferences(ReaderWireModel):
    direction: Literal["ltr", "rtl"] = "ltr"
    mode: Literal["single", "double"] = "single"
    page_turn_animation: Literal["slide", "off"] = Field("slide", alias="pageTurnAnimation")
    image_fit: Literal["width", "height", "contain", "original"] = Field("width", alias="imageFit")
    image_variant: Literal["original", "data-saver"] = Field("original", alias="imageVariant")
    zoom: float = Field(1.0, ge=0.6, le=2.4)


class PdfPreferences(ReaderWireModel):
    zoom: float = Field(1.0, ge=0.6, le=2.4)
    fit: Literal["width", "page"] = "page"


class AudioPreferences(ReaderWireModel):
    playback_rate: float = Field(1.0, alias="playbackRate", ge=0.75, le=3.0)
    skip_backward_seconds: int = Field(15, alias="skipBackwardSeconds", ge=5, le=120)
    skip_forward_seconds: int = Field(30, alias="skipForwardSeconds", ge=5, le=120)
    volume: float = Field(1.0, ge=0, le=1)


class ReaderPreferences(ReaderWireModel):
    schema_version: Literal[3] = Field(3, alias="schemaVersion")
    appearance: AppearancePreferences = Field(default_factory=AppearancePreferences)
    epub: EpubPreferences = Field(default_factory=EpubPreferences)
    comic: ComicPreferences = Field(default_factory=ComicPreferences)
    pdf: PdfPreferences = Field(default_factory=PdfPreferences)
    audio: AudioPreferences = Field(default_factory=AudioPreferences)

    @field_validator("schema_version", mode="before")
    @classmethod
    def migrate_v2_schema(cls, value: object) -> object:
        return 3 if value == 2 else value


class EpubLocation(ReaderWireModel):
    type: Literal["epub"]
    cfi: str | None = Field(default=None, min_length=1, max_length=4096)
    href: str | None = Field(default=None, min_length=1, max_length=2048)
    spine_index: int | None = Field(default=None, alias="spineIndex", ge=0)
    progression: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_anchor(self) -> EpubLocation:
        if self.cfi is None and self.href is None and self.spine_index is None and self.progression is None:
            raise ValueError("EPUB location requires cfi, href, spineIndex, or progression")
        return self


class ComicLocation(ReaderWireModel):
    type: Literal["comic"]
    volume_id: str = Field(alias="volumeId", min_length=1, max_length=191)
    page_index: int = Field(alias="pageIndex", ge=1)


class PdfLocation(ReaderWireModel):
    type: Literal["pdf"]
    page_number: int = Field(alias="pageNumber", ge=1)


class AudioLocation(ReaderWireModel):
    type: Literal["audio"]
    volume_id: str | None = Field(default=None, alias="volumeId", max_length=191)
    file_id: str = Field(alias="fileId", min_length=1, max_length=191)
    chapter_id: str | None = Field(default=None, alias="chapterId", max_length=191)
    position_ms: int = Field(alias="positionMs", ge=0)


ReaderLocation = Annotated[EpubLocation | ComicLocation | PdfLocation | AudioLocation, Field(discriminator="type")]


class ReaderProgressPut(ReaderWireModel):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    user_id: str = Field(alias="userId", min_length=1, max_length=191)
    mutation_id: str = Field(alias="mutationId", min_length=1, max_length=191)
    client_id: str = Field(alias="clientId", min_length=1, max_length=191)
    client_sequence: int = Field(alias="clientSequence", ge=0)
    content_fingerprint: str = Field(alias="contentFingerprint", min_length=1, max_length=191)
    volume_id: str | None = Field(default=None, alias="volumeId", max_length=191)
    location: ReaderLocation
    percent: float = Field(ge=0, le=100)


class EpubLocationsClaimRequest(ReaderWireModel):
    cache_version: Literal[2] = Field(alias="cacheVersion")
    content_fingerprint: str = Field(alias="contentFingerprint", min_length=1, max_length=191)
    break_size: int = Field(alias="breakSize", ge=100, le=10000)


class EpubLocationsSaveRequest(EpubLocationsClaimRequest):
    lease_token: str = Field(alias="leaseToken", min_length=1, max_length=191)
    serialized: str = Field(min_length=1, max_length=64 * 1024 * 1024)


class ReaderBookSummary(ReaderWireModel):
    id: str
    title: str
    author: str | None = None
    cover_url: str | None = Field(default=None, alias="coverUrl")


class ReaderEditionSummary(ReaderWireModel):
    id: str
    work_id: str = Field(alias="workId")
    format: ReaderFormat
    version_name: str = Field(alias="versionName")
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    media_kind: Literal["EBOOK", "COMIC", "AUDIOBOOK"] | None = Field(default=None, alias="mediaKind")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    track_count: int | None = Field(default=None, alias="trackCount")
    narrator: str | None = None


class ReaderVolumeSummary(ReaderWireModel):
    id: str
    title: str
    index: float
    page_count: int | None = Field(default=None, alias="pageCount")
    chapter_count: int | None = Field(default=None, alias="chapterCount")
    duration_ms: int | None = Field(default=None, alias="durationMs")


class ReaderEditionOption(ReaderEditionSummary):
    progress: float = Field(ge=0, le=100)
    last_read_at: datetime | None = Field(alias="lastReadAt")
    volumes: list[ReaderVolumeSummary]


class ReaderUnitSummary(ReaderWireModel):
    id: str | None = None
    index: int
    title: str
    href: str | None = None
    file_id: str | None = Field(default=None, alias="fileId")
    start_ms: int | None = Field(default=None, alias="startMs", ge=0)
    end_ms: int | None = Field(default=None, alias="endMs", ge=0)
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0)


class AudioTrackSummary(ReaderWireModel):
    file_id: str = Field(alias="fileId")
    title: str
    url: str
    mime_type: str = Field(alias="mimeType")
    duration_ms: int = Field(alias="durationMs", ge=0)
    disc_number: int | None = Field(default=None, alias="discNumber")
    track_number: int | None = Field(default=None, alias="trackNumber")
    sort_order: int = Field(alias="sortOrder")


class AudioChapterSummary(ReaderWireModel):
    id: str
    title: str
    file_id: str = Field(alias="fileId")
    start_ms: int = Field(alias="startMs", ge=0)
    end_ms: int = Field(alias="endMs", ge=0)
    duration_ms: int = Field(alias="durationMs", ge=0)
    sort_order: int = Field(alias="sortOrder")


class ReaderPageSummary(ReaderWireModel):
    page_index: int = Field(alias="pageIndex", ge=1)
    title: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    width: int | None = None
    height: int | None = None
    size: int | None = None


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
    reading_direction: Literal["ltr", "rtl"] = Field(alias="readingDirection")


class ReaderServerPreferences(ReaderWireModel):
    schema_version: Literal[3] = Field(3, alias="schemaVersion")
    settings: ReaderPreferences
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    @field_validator("schema_version", mode="before")
    @classmethod
    def migrate_v2_schema(cls, value: object) -> object:
        return 3 if value == 2 else value


class ReaderBootstrapData(ReaderWireModel):
    schema_version: Literal[2] = Field(2, alias="schemaVersion")
    user_id: str = Field(alias="userId")
    reader_type: ReaderFormat = Field(alias="readerType")
    content_fingerprint: str = Field(alias="contentFingerprint")
    book: ReaderBookSummary
    edition: ReaderEditionSummary
    available_editions: list[ReaderEditionOption] = Field(alias="availableEditions")
    selected_volume: ReaderVolumeSummary | None = Field(default=None, alias="selectedVolume")
    volumes: list[ReaderVolumeSummary]
    units: list[ReaderUnitSummary]
    pages: list[ReaderPageSummary]
    tracks: list[AudioTrackSummary] = Field(default_factory=list)
    chapters: list[AudioChapterSummary] = Field(default_factory=list)
    total_duration_ms: int | None = Field(default=None, alias="totalDurationMs", ge=0)
    total_pages: int | None = Field(default=None, alias="totalPages")
    file_url: str = Field(alias="fileUrl")
    capabilities: ReaderCapabilities
    server_preferences: ReaderServerPreferences = Field(alias="serverPreferences")
    resume_location: ReaderLocation | None = Field(default=None, alias="resumeLocation")
    resume_fingerprint_mismatch: bool = Field(False, alias="resumeFingerprintMismatch")
    resume_discarded_reason: Literal["content_fingerprint_mismatch"] | None = Field(default=None, alias="resumeDiscardedReason")
    progress_percent: float = Field(0, alias="progressPercent", ge=0, le=100)


class ReaderProgressRecord(ReaderWireModel):
    schema_version: Literal[2] = Field(2, alias="schemaVersion")
    mutation_id: str = Field(alias="mutationId")
    client_id: str = Field(alias="clientId")
    client_sequence: int = Field(alias="clientSequence")
    content_fingerprint: str = Field(alias="contentFingerprint")
    reader_type: ReaderFormat = Field(alias="readerType")
    work_id: str = Field(alias="workId")
    edition_id: str = Field(alias="editionId")
    volume_id: str | None = Field(default=None, alias="volumeId")
    location: ReaderLocation
    percent: float
    updated_at: datetime = Field(alias="updatedAt")


class ReaderBootstrapResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderBootstrapData


class ReaderProgressData(ReaderWireModel):
    mutation_id: str = Field(alias="mutationId")
    applied: bool
    progress: ReaderProgressRecord


class ReaderProgressResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderProgressData


class ReaderBookmarkLocation(ReaderWireModel):
    kind: Literal["epub", "comic", "pdf", "audio"]
    href: str | None = None
    spine_index: int | None = Field(default=None, alias="spineIndex", ge=0)
    progression: float | None = Field(default=None, ge=0, le=1)
    page_index: int | None = Field(default=None, alias="pageIndex", ge=1)
    page_number: int | None = Field(default=None, alias="pageNumber", ge=1)
    volume_id: str | None = Field(default=None, alias="volumeId")
    file_id: str | None = Field(default=None, alias="fileId")
    chapter_id: str | None = Field(default=None, alias="chapterId")
    position_ms: int | None = Field(default=None, alias="positionMs", ge=0)


class ReaderBookmark(ReaderWireModel):
    id: str = Field(min_length=1, max_length=2000)
    location: ReaderBookmarkLocation
    label: str = Field(max_length=500)
    percent: float = Field(ge=0, le=100)
    created_at: datetime = Field(alias="createdAt")


class ReaderBookmarksReplaceRequest(ReaderWireModel):
    content_fingerprint: str = Field(alias="contentFingerprint", min_length=1, max_length=191)
    bookmarks: list[ReaderBookmark] = Field(max_length=500)


class ReaderBookmarksData(ReaderWireModel):
    bookmarks: list[ReaderBookmark]


class ReaderBookmarksResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: ReaderBookmarksData


class EpubLocationsReady(ReaderWireModel):
    status: Literal["ready"]
    serialized: str


class EpubLocationsGenerating(ReaderWireModel):
    status: Literal["generating"]
    lease_expires_at: int = Field(alias="leaseExpiresAt")
    retry_after_ms: int = Field(alias="retryAfterMs")


class EpubLocationsClaimed(ReaderWireModel):
    status: Literal["claimed"]
    lease_token: str = Field(alias="leaseToken")
    lease_expires_at: int = Field(alias="leaseExpiresAt")


EpubLocationsResult = Annotated[
    EpubLocationsReady | EpubLocationsGenerating | EpubLocationsClaimed,
    Field(discriminator="status"),
]


class EpubLocationsResponse(ReaderWireModel):
    ok: Literal[True] = True
    data: EpubLocationsResult


class ReaderErrorDetails(ReaderWireModel):
    expected_content_fingerprint: str = Field(alias="expectedContentFingerprint")
    received_content_fingerprint: str = Field(alias="receivedContentFingerprint")
    edition_id: str = Field(alias="editionId")
    volume_id: str | None = Field(alias="volumeId")


class ReaderErrorBody(ReaderWireModel):
    message: str
    code: str | None = Field(default=None, exclude_if=lambda value: value is None)
    details: ReaderErrorDetails | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ReaderUnauthorizedError(HttpContractError[ReaderErrorBody]):
    status_code = 401
    body_model = ReaderErrorBody


class ReaderForbiddenError(HttpContractError[ReaderErrorBody]):
    status_code = 403
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


class ReaderUnavailableError(HttpContractError[ReaderErrorBody]):
    status_code = 503
    body_model = ReaderErrorBody
