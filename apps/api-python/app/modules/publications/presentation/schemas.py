"""Readium Web Publication Manifest and Positions List schemas."""

from __future__ import annotations

from typing import Literal

from fastapi.responses import Response
from pydantic import Field

from app.contracts.http import HttpContractModel


class PublicationMetadata(HttpContractModel):
    schema_type: Literal["http://schema.org/Book"] = Field(
        default="http://schema.org/Book",
        alias="@type",
    )
    identifier: str
    title: str
    conforms_to: list[str] = Field(alias="conformsTo")
    layout: Literal["reflowable"] = "reflowable"
    reading_progression: Literal["ltr", "rtl"] = Field(alias="readingProgression")
    author: str | None = None
    language: str | None = None


class PublicationLink(HttpContractModel):
    href: str
    type: str
    title: str | None = None
    rel: list[str] | None = None


class PublicationTocEntry(HttpContractModel):
    href: str
    title: str
    children: list[PublicationTocEntry] | None = None


class PublicationRuntimeFingerprint(HttpContractModel):
    original_file_hash: str = Field(alias="originalFileHash")
    parser: str
    normalization: str
    position_page_length: int = Field(default=1024, alias="positionPageLength")


class PublicationManifest(HttpContractModel):
    context: Literal["https://readium.org/webpub-manifest/context.jsonld"] = Field(
        default="https://readium.org/webpub-manifest/context.jsonld",
        alias="@context",
    )
    metadata: PublicationMetadata
    links: list[PublicationLink]
    reading_order: list[PublicationLink] = Field(alias="readingOrder")
    resources: list[PublicationLink]
    toc: list[PublicationTocEntry]
    runtime: PublicationRuntimeFingerprint = Field(
        alias="https://shuku.app/reader/runtime"
    )


class PositionLocations(HttpContractModel):
    position: int = Field(ge=1)
    progression: float = Field(ge=0, le=1)
    total_progression: float = Field(alias="totalProgression", ge=0, le=1)


class PublicationPosition(HttpContractModel):
    href: str
    type: str
    locations: PositionLocations


class PublicationPositions(HttpContractModel):
    total: int = Field(ge=1)
    positions: list[PublicationPosition]


class PublicationResourceResponse(Response):
    """Opaque publication resource whose concrete media type comes from its manifest."""

    media_type = "application/octet-stream"
