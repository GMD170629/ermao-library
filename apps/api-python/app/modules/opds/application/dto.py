from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

OPDS_ACQUISITION_REL = "http://opds-spec.org/acquisition"
OPDS_PROGRESSION_REL = "http://opds-spec.org/progression"
OPDS_PROGRESSION_MEDIA_TYPE = "application/opds-progression+json"
PSE_STREAM_REL = "http://vaemendis.net/opds-pse/stream"
PSE_MEDIA_TYPES = frozenset({"image/jpeg", "image/gif", "image/png"})


@dataclass(frozen=True, slots=True)
class OpdsActorDto:
    user_id: str


@dataclass(frozen=True, slots=True)
class BasicCredentialsDto:
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OpdsAuthenticationRequestDto:
    credentials: BasicCredentialsDto = field(repr=False)
    client_address: str
    method: str
    path: str


@dataclass(frozen=True, slots=True)
class OpdsLinkDto:
    href: str
    rel: str
    media_type: str
    title: str | None = None

    def __post_init__(self) -> None:
        if not self.href or not self.rel or not self.media_type:
            raise ValueError("OPDS links require href, rel, and media_type")


@dataclass(frozen=True, slots=True)
class OpdsAuthorDto:
    name: str
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class PseStreamDto:
    href_template: str
    media_type: str
    page_count: int
    last_read: int | None = None
    last_read_date: datetime | None = None

    def __post_init__(self) -> None:
        if "{pageNumber}" not in self.href_template:
            raise ValueError("PSE href_template must contain {pageNumber}")
        if self.media_type not in PSE_MEDIA_TYPES:
            raise ValueError("PSE stream media_type must be JPEG, GIF, or PNG")
        if self.page_count < 1:
            raise ValueError("PSE page_count must be positive")
        if self.last_read is not None and not 1 <= self.last_read <= self.page_count:
            raise ValueError("PSE last_read is 1-based and must be within page_count")
        if self.last_read_date is not None:
            if self.last_read is None:
                raise ValueError("PSE last_read_date requires last_read")
            if (
                self.last_read_date.tzinfo is None
                or self.last_read_date.utcoffset() is None
            ):
                raise ValueError("PSE last_read_date must include a timezone")


@dataclass(frozen=True, slots=True)
class OpdsEntryDto:
    id: str
    title: str
    updated_at: datetime
    authors: tuple[OpdsAuthorDto, ...] = ()
    summary: str | None = None
    links: tuple[OpdsLinkDto, ...] = ()
    pse_stream: PseStreamDto | None = None


@dataclass(frozen=True, slots=True)
class OpdsFeedDto:
    id: str
    title: str
    updated_at: datetime
    kind: Literal["navigation", "acquisition"]
    self_url: str
    start_url: str
    entries: tuple[OpdsEntryDto, ...]
    total_results: int
    start_index: int
    items_per_page: int
    search_url_template: str | None = None
    next_url: str | None = None
    previous_url: str | None = None

    def __post_init__(self) -> None:
        if self.total_results < 0 or self.start_index < 0:
            raise ValueError("OpenSearch counts cannot be negative")
        if self.items_per_page < 1:
            raise ValueError("items_per_page must be positive")


@dataclass(frozen=True, slots=True)
class OpdsCatalogQueryDto:
    actor_id: str
    public_base_url: str
    search: str | None
    page: int
    page_size: int
    view: str = "catalog"
    resource_id: str | None = None


@dataclass(frozen=True, slots=True)
class PsePageRequestDto:
    actor_id: str
    volume_id: str
    page_number: int
    max_width: int | None

    def __post_init__(self) -> None:
        if self.page_number < 0:
            raise ValueError("PSE page_number is 0-based and cannot be negative")
        if self.max_width is not None and self.max_width < 1:
            raise ValueError("PSE max_width must be positive")

    @property
    def internal_page_index(self) -> int:
        """Translate the PSE 0-based page number to Shuku's 1-based index."""

        return self.page_number + 1


@dataclass(frozen=True, slots=True)
class OpdsProgressionDeviceDto:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class OpdsProgressionDocumentDto:
    modified: datetime
    device: OpdsProgressionDeviceDto
    progression: float
    title: str | None = None
    references: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class OpdsProgressionUpdateResultDto:
    created: bool
    document: OpdsProgressionDocumentDto


def select_pse_stream_media_type(page_media_types: tuple[str, ...]) -> str:
    """Choose the one MIME type an OPDS-PSE link is allowed to advertise."""

    normalized = tuple(
        value.split(";", 1)[0].strip().lower() for value in page_media_types
    )
    if normalized and len(set(normalized)) == 1 and normalized[0] in PSE_MEDIA_TYPES:
        return normalized[0]
    return "image/jpeg"


def normalize_pse_max_width(requested_width: int | None) -> int | None:
    """Bound cache variants while never exceeding the client's requested width."""

    if requested_width is None:
        return None
    if requested_width < 1:
        raise ValueError("PSE maxWidth must be positive")
    bounded = min(requested_width, 2560)
    buckets = (640, 960, 1280, 1600, 2048, 2560)
    eligible = tuple(width for width in buckets if width <= bounded)
    return eligible[-1] if eligible else bounded
