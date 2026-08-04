"""Pure media-version and volume-resource import rules.

The importer has exactly one media version for each ``(work, media kind)``.
Files are independently addressable volumes; descriptive volume numbers never
participate in identity or uniqueness.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath


class MediaKind(StrEnum):
    EBOOK = "EBOOK"
    COMIC = "COMIC"
    AUDIOBOOK = "AUDIOBOOK"


class VolumeFormat(StrEnum):
    EPUB = "EPUB"
    MOBI = "MOBI"
    AZW = "AZW"
    AZW3 = "AZW3"
    PRC = "PRC"
    FB2 = "FB2"
    TXT = "TXT"
    PDF = "PDF"
    CBR = "CBR"
    CBZ = "CBZ"
    RAR = "RAR"
    ZIP = "ZIP"
    M4B = "M4B"
    M4A = "M4A"
    MP3 = "MP3"

    @property
    def media_kind(self) -> MediaKind:
        if self in {
            VolumeFormat.CBR,
            VolumeFormat.CBZ,
            VolumeFormat.RAR,
            VolumeFormat.ZIP,
        }:
            return MediaKind.COMIC
        if self in {VolumeFormat.M4B, VolumeFormat.M4A, VolumeFormat.MP3}:
            return MediaKind.AUDIOBOOK
        return MediaKind.EBOOK

    @classmethod
    def from_name(cls, value: str) -> VolumeFormat:
        normalized = value.strip().removeprefix(".").upper()
        return cls(normalized)


@dataclass(frozen=True, slots=True)
class EnsureMediaVersion:
    work_id: str
    media_kind: MediaKind


@dataclass(frozen=True, slots=True)
class CreateVolumeResource:
    media_version_id: str
    source_path: str
    format: VolumeFormat
    title: str
    volume_index: float | None
    source_fingerprint: str | None = None
    derived_from_volume_id: str | None = None

    @property
    def resource_key(self) -> str:
        """Stable path resource identity; never includes the volume number."""

        normalized_path = str(PurePath(self.source_path)).replace("\\", "/")
        payload = f"{self.media_version_id}\0{normalized_path.casefold()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def natural_name_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Wiki-compatible case-insensitive natural filename ordering."""

    parts = re.split(r"(\d+)", value.casefold())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in parts if part
    )


def initial_volume_order(
    resources: list[CreateVolumeResource],
) -> list[CreateVolumeResource]:
    """Return a deterministic first-import order without enforcing uniqueness."""

    return sorted(
        resources,
        key=lambda resource: (
            resource.volume_index is None,
            resource.volume_index if resource.volume_index is not None else 0,
            natural_name_key(PurePath(resource.source_path).name),
            resource.resource_key,
        ),
    )
