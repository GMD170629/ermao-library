"""Reader v5 HTTP contracts.

The Locator is intentionally represented as a recursive JSON object.  The
backend validates only JSON shape and the transport budget; it must not inspect
any Locator member.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypeAlias
from uuid import UUID

from fastapi.responses import Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    model_validator,
)
from typing_extensions import TypeAliasType

from app.contracts.http_errors import HttpContractError
from app.modules.reader.presentation.common_schemas import (
    ReaderAssetSummary,
    ReaderBookSummary,
    ReaderCapabilities,
    ReaderNavigationUnitSummary,
    ReaderPublicationAccess,
    ReaderResourceSummary,
    ReaderSourceFormat,
)


class ReaderV5WireModel(BaseModel):
    # Readium locators and the client-owned projection are JSON transport
    # values.  Non-finite IEEE-754 values are not JSON and must be rejected at
    # the HTTP boundary, before the opaque mapper or persistence layer sees
    # them.
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        allow_inf_nan=False,
    )


class ReaderV5PublicationResourceResponse(Response):
    """Documentation response class for a format-dependent publication byte."""

    media_type = "application/octet-stream"


if TYPE_CHECKING:
    ReaderV5JsonValue: TypeAlias = (
        str
        | int
        | float
        | bool
        | None
        | list["ReaderV5JsonValue"]
        | dict[str, "ReaderV5JsonValue"]
    )
else:
    ReaderV5JsonValue = TypeAliasType(
        "ReaderV5JsonValue",
        str
        | int
        | float
        | bool
        | None
        | list["ReaderV5JsonValue"]
        | dict[str, "ReaderV5JsonValue"],
    )


OpaqueLocator: TypeAlias = dict[str, ReaderV5JsonValue]

_MAX_LOCATOR_BYTES = 65_536


def _compact_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class ReaderV5Chapter(ReaderV5WireModel):
    href: str | None = Field(max_length=8192)
    title: str | None = Field(max_length=4096)
    index: StrictInt | None = Field(ge=0)


class ReaderV5Page(ReaderV5WireModel):
    number: StrictInt = Field(ge=1)
    total: StrictInt | None = Field(ge=1)


class ReaderV5Playback(ReaderV5WireModel):
    position_millis: StrictInt = Field(alias="positionMillis", ge=0)
    duration_millis: StrictInt | None = Field(alias="durationMillis", ge=0)


class ReaderV5Presentation(ReaderV5WireModel):
    display_percent: StrictFloat = Field(alias="displayPercent", ge=0, le=100)
    total_progression: StrictFloat = Field(alias="totalProgression", ge=0, le=1)
    current_href: str | None = Field(alias="currentHref", max_length=8192)
    chapter: ReaderV5Chapter | None
    page: ReaderV5Page | None
    playback: ReaderV5Playback | None


class ReaderV5Position(ReaderV5WireModel):
    locator: OpaqueLocator
    presentation: ReaderV5Presentation

    @model_validator(mode="after")
    def require_bounded_locator(self) -> ReaderV5Position:
        encoded = _compact_json(self.locator)
        if len(encoded) > _MAX_LOCATOR_BYTES:
            raise ValueError("Reader v5 Locator exceeds 64 KiB")
        return self


class ReaderV5ProgressPut(ReaderV5WireModel):
    schema_version: Literal[5] = Field(alias="schemaVersion")
    client_id: str = Field(
        alias="clientId", min_length=1, max_length=256, pattern=r"\S"
    )
    mutation_id: UUID = Field(alias="mutationId")
    captured_at_epoch_millis: StrictInt = Field(alias="capturedAtEpochMillis", ge=0)
    position: ReaderV5Position


class ReaderV5ProgressSnapshot(ReaderV5WireModel):
    schema_version: Literal[5] = Field(alias="schemaVersion")
    revision: StrictInt = Field(ge=1)
    client_id: str = Field(
        alias="clientId", min_length=1, max_length=256, pattern=r"\S"
    )
    mutation_id: UUID = Field(alias="mutationId")
    captured_at_epoch_millis: StrictInt = Field(alias="capturedAtEpochMillis", ge=0)
    received_at_epoch_millis: StrictInt = Field(alias="receivedAtEpochMillis", ge=0)
    position: ReaderV5Position


class ReaderV5ProgressStateData(ReaderV5WireModel):
    schema_version: Literal[5] = Field(alias="schemaVersion")
    progress_snapshot: ReaderV5ProgressSnapshot | None = Field(alias="progressSnapshot")


class ReaderV5ProgressStateResponse(ReaderV5WireModel):
    ok: Literal[True]
    data: ReaderV5ProgressStateData


class ReaderV5ProgressWriteData(ReaderV5WireModel):
    accepted_mutation_id: UUID = Field(alias="acceptedMutationId")
    accepted_revision: StrictInt = Field(alias="acceptedRevision", ge=1)
    current_snapshot: ReaderV5ProgressSnapshot = Field(alias="currentSnapshot")


class ReaderV5ProgressWriteResponse(ReaderV5WireModel):
    ok: Literal[True]
    data: ReaderV5ProgressWriteData


class ReaderV5Bookmark(ReaderV5WireModel):
    id: str = Field(min_length=1, max_length=5000)
    position: ReaderV5Position
    label: str = Field(max_length=500)
    created_at: datetime = Field(alias="createdAt")


class ReaderV5BookmarksReplaceRequest(ReaderV5WireModel):
    bookmarks: list[ReaderV5Bookmark] = Field(max_length=500)

    @model_validator(mode="after")
    def require_unique_bookmark_ids(self) -> ReaderV5BookmarksReplaceRequest:
        bookmark_ids = [bookmark.id for bookmark in self.bookmarks]
        if len(bookmark_ids) != len(set(bookmark_ids)):
            raise ValueError("Bookmark IDs must be unique within a resource")
        return self


class ReaderV5BookmarksData(ReaderV5WireModel):
    bookmarks: list[ReaderV5Bookmark]


class ReaderV5BookmarksResponse(ReaderV5WireModel):
    ok: Literal[True]
    data: ReaderV5BookmarksData


class ReaderV5BootstrapData(ReaderV5WireModel):
    schema_version: Literal[5] = Field(5, alias="schemaVersion")
    user_id: str = Field(alias="userId")
    reader_type: Literal["reflowable", "comic", "pdf", "audio"] = Field(
        alias="readerType"
    )
    source_format: ReaderSourceFormat = Field(alias="sourceFormat")
    book: ReaderBookSummary
    resource: ReaderResourceSummary
    available_resources: list[ReaderResourceSummary] = Field(alias="availableResources")
    assets: list[ReaderAssetSummary]
    units: list[ReaderNavigationUnitSummary]
    resource_url: str = Field(alias="resourceUrl")
    capabilities: ReaderCapabilities
    publication: ReaderPublicationAccess | None = None
    progress_snapshot: ReaderV5ProgressSnapshot | None = Field(
        default=None, alias="progressSnapshot"
    )


class ReaderV5BootstrapResponse(ReaderV5WireModel):
    ok: Literal[True]
    data: ReaderV5BootstrapData


class ReaderV5ErrorBody(ReaderV5WireModel):
    message: str = Field(min_length=1, max_length=4096)
    code: str | None = None


class ReaderV5MutationReuseBody(ReaderV5WireModel):
    message: str = Field(min_length=1, max_length=4096)
    code: Literal["READER_PROGRESS_MUTATION_REUSE"] = "READER_PROGRESS_MUTATION_REUSE"


class ReaderV5UnauthorizedError(HttpContractError[ReaderV5ErrorBody]):
    status_code = 401
    body_model = ReaderV5ErrorBody


class ReaderV5NotFoundError(HttpContractError[ReaderV5ErrorBody]):
    status_code = 404
    body_model = ReaderV5ErrorBody


class ReaderV5ValidationError(HttpContractError[ReaderV5ErrorBody]):
    status_code = 422
    body_model = ReaderV5ErrorBody


class ReaderV5MutationReuseError(HttpContractError[ReaderV5MutationReuseBody]):
    status_code = 409
    body_model = ReaderV5MutationReuseBody


__all__ = [
    "OpaqueLocator",
    "ReaderV5Bookmark",
    "ReaderV5BookmarksData",
    "ReaderV5BookmarksReplaceRequest",
    "ReaderV5BookmarksResponse",
    "ReaderV5BootstrapData",
    "ReaderV5BootstrapResponse",
    "ReaderV5Chapter",
    "ReaderV5ErrorBody",
    "ReaderV5JsonValue",
    "ReaderV5MutationReuseBody",
    "ReaderV5MutationReuseError",
    "ReaderV5NotFoundError",
    "ReaderV5Page",
    "ReaderV5Playback",
    "ReaderV5Position",
    "ReaderV5Presentation",
    "ReaderV5ProgressPut",
    "ReaderV5ProgressSnapshot",
    "ReaderV5ProgressStateData",
    "ReaderV5ProgressStateResponse",
    "ReaderV5ProgressWriteData",
    "ReaderV5ProgressWriteResponse",
    "ReaderV5PublicationResourceResponse",
    "ReaderV5UnauthorizedError",
    "ReaderV5ValidationError",
]
