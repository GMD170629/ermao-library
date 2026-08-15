"""Render artifact identities and cache state."""

from __future__ import annotations

from dataclasses import dataclass

RENDER_ARTIFACT_MEDIA_TYPE = "application/epub+zip"
RENDER_ARTIFACT_SCHEMA_VERSION = 1
RENDER_NORMALIZATION_IDENTIFIER = "shuku-render-html5-v1"


@dataclass(frozen=True, slots=True)
class PreparedPublicationRenderArtifact:
    content: bytes
    size_bytes: int
    source_size_bytes: int
    source_mtime_ms: int
    source_parser: str
    normalization: str
    unreadable_hrefs: tuple[str, ...]
    recovered_resource_count: int


@dataclass(frozen=True, slots=True)
class PublicationRenderArtifact:
    volume_id: str
    file_id: str
    source_size_bytes: int
    source_mtime_ms: int
    parser: str
    normalization: str
    relative_path: str
    size_bytes: int
    unreadable_resource_count: int


__all__ = [
    "RENDER_ARTIFACT_MEDIA_TYPE",
    "RENDER_ARTIFACT_SCHEMA_VERSION",
    "RENDER_NORMALIZATION_IDENTIFIER",
    "PreparedPublicationRenderArtifact",
    "PublicationRenderArtifact",
]
