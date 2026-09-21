"""Explicit file metadata observations; no source priority or database mutations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.publication_metadata import PublicationMetadata

MetadataFileSource = Literal["embedded", "sidecar"]


class StandardMetadataError(ValueError):
    """A safe code for failed or unsupported standard-format operations."""


@dataclass(frozen=True)
class StandardMetadataObservation:
    source: MetadataFileSource
    relative_path: str
    format: str
    file_revision: str
    metadata: PublicationMetadata
    writable_fields: tuple[str, ...] = ()


class StandardFileMetadataReader(Protocol):
    def read(
        self,
        root: Path,
        relative_path: str,
        *,
        directory: bool,
        source: MetadataFileSource,
        sidecar_relative_path: str | None = None,
    ) -> StandardMetadataObservation: ...
