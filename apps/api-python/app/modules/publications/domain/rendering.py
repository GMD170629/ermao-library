"""Render artifact identities and cache state."""

from __future__ import annotations

from dataclasses import dataclass

RENDER_ARTIFACT_MEDIA_TYPE = "application/epub+zip"
RENDER_ARTIFACT_SCHEMA_VERSION = 1
RENDER_NORMALIZATION_IDENTIFIER = "shuku-render-html5-v1"


@dataclass(frozen=True, slots=True)
class PreparedPublicationRenderArtifact:
    content: bytes
    content_hash: str
    size_bytes: int
    original_file_hash: str
    source_parser: str
    normalization: str
    unreadable_hrefs: tuple[str, ...]
    recovered_resource_count: int


@dataclass(frozen=True, slots=True)
class PublicationRenderArtifact:
    volume_id: str
    file_id: str
    original_file_hash: str
    parser: str
    normalization: str
    relative_path: str
    content_hash: str
    size_bytes: int
    unreadable_resource_count: int


__all__ = [
    "RENDER_ARTIFACT_MEDIA_TYPE",
    "RENDER_ARTIFACT_SCHEMA_VERSION",
    "RENDER_NORMALIZATION_IDENTIFIER",
    "PreparedPublicationRenderArtifact",
    "PublicationRenderArtifact",
]
