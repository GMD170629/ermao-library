"""Framework-independent audiobook metadata contracts and constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

SUPPORTED_AUDIO_EXTS = {".m4b", ".m4a", ".mp3"}
MAX_AUDIO_CHAPTERS = 10_000
DISC_DIRECTORY_PATTERN = re.compile(
    r"^(?:cd|disc|disk|碟|盘)\s*[-_. ]*\d+(?:\s*(?:of|/|[-–—])\s*\d+)?$",
    re.I,
)
_EXPLICIT_EPISODE_PATTERN = re.compile(
    r"第\s*0*(\d{1,6})\s*[集章回节]",
    re.I,
)
_PREFIXED_EPISODE_PATTERN = re.compile(
    r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?"
    r"(?:(?:track|chapter|chap|ch)\s*)?"
    r"[\[(]?0*(\d{1,6})[\])]?"
    r"(?:\s*[集章回节])?(?:[ ._-]+|$)",
    re.I,
)
_FALLBACK_EPISODE_PATTERN = re.compile(r"(?<!\d)0*(\d{1,6})(?!\d)")


@dataclass(frozen=True)
class AudioChapterMetadata:
    title: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AudioFileMetadata:
    path: Path
    title: str | None
    album: str | None
    author: str | None
    narrator: str | None
    duration_ms: int
    codec: str
    bitrate: int | None
    sample_rate: int | None
    channels: int | None
    disc_number: int | None
    track_number: int | None
    chapters: tuple[AudioChapterMetadata, ...] = ()
    raw_tags: Mapping[str, object] = field(default_factory=dict)
    cover_data: bytes | None = None
    cover_extension: str | None = None


@dataclass(frozen=True)
class AudioVolumeDirectory:
    path: Path
    title: str
    volume_index: float | None
    author: str | None
    files: tuple[Path, ...]


@dataclass(frozen=True)
class AudioBundleStructure:
    root: Path
    title: str
    author: str | None
    volumes: tuple[AudioVolumeDirectory, ...]

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(path for volume in self.volumes for path in volume.files)

    @property
    def is_multi_volume(self) -> bool:
        return len(self.volumes) > 1 or bool(
            self.volumes and self.volumes[0].path != self.root
        )


def is_supported_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTS


def audio_episode_number(path: str | Path) -> int | None:
    """Extract an episode number using explicit rules before a numeric fallback."""

    stem = Path(path).stem
    explicit = _EXPLICIT_EPISODE_PATTERN.search(stem)
    if explicit:
        return int(explicit.group(1))
    prefixed = _PREFIXED_EPISODE_PATTERN.match(stem)
    if prefixed:
        return int(prefixed.group(1))
    fallback = _FALLBACK_EPISODE_PATTERN.search(stem)
    return int(fallback.group(1)) if fallback else None
