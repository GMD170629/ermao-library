"""Framework-independent audiobook metadata contracts and constants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_AUDIO_PROFILE,
    READER_SAFETY_FORMATS,
    ReaderSafetyBudgetName,
    ReaderSafetyFormatLifecycle,
    ReaderSafetyMorphology,
    reader_safety_budget,
)

SUPPORTED_AUDIO_EXTS = frozenset(READER_SAFETY_AUDIO_PROFILE.container_mime_types)
LEGACY_AUDIO_EXTS = frozenset(
    policy.extension
    for policy in READER_SAFETY_FORMATS.values()
    if policy.morphology is ReaderSafetyMorphology.AUDIO
    and policy.lifecycle is ReaderSafetyFormatLifecycle.RECEIVE_ONLY
    and policy.extension is not None
)
NEW_AUDIO_EXTS = SUPPORTED_AUDIO_EXTS - LEGACY_AUDIO_EXTS

MAX_AUDIO_CHAPTERS = reader_safety_budget(
    ReaderSafetyBudgetName.AUDIO_CHAPTER_MAX_COUNT
)
MAX_AUDIO_BUNDLE_TRACKS = reader_safety_budget(
    ReaderSafetyBudgetName.AUDIO_TRACK_MAX_COUNT
)
_EXPLICIT_EPISODE_PATTERN = re.compile(
    r"第\s*0*(\d{1,6})\s*[集章回节]",
    re.IGNORECASE,
)
_PREFIXED_EPISODE_PATTERN = re.compile(
    r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?"
    r"(?:(?:track|chapter|chap|ch)\s*)?"
    r"[\[(]?0*(\d{1,6})[\])]?"
    r"(?:\s*[集章回节])?(?:[ ._-]+|$)",
    re.IGNORECASE,
)
_FALLBACK_EPISODE_PATTERN = re.compile(r"(?<!\d)0*(\d{1,6})(?!\d)")
_STRICT_FLAT_AUDIO_PATTERN = re.compile(
    r"^\s*0*\d{1,6}\s*[-\u2013\u2014_.]+\s*(?P<title>.+?)\s*"
    r"[-\u2013\u2014]+\s*"
    r"(?:(?:chapter|chap|ch|track|part|episode|ep)\s*0*\d{1,6}\b|"
    r"\u7b2c?\s*0*\d{1,6}\s*[\u7ae0\u56de\u96c6\u8282]).*$",
    re.IGNORECASE,
)


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
    series_name: str | None = None
    volume_index: float | None = None
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


def audio_mime_type(path: str | Path) -> str:
    """Return the stable HTTP media type for an admitted audio container."""

    extension = Path(path).suffix.lower()
    try:
        return READER_SAFETY_AUDIO_PROFILE.container_mime_types[extension]
    except KeyError as error:
        raise ValueError(
            f"unsupported admitted audio extension: {extension}"
        ) from error


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


def strict_flat_audio_title(path: str | Path) -> str | None:
    """Extract the book title from the documented library-root flat layout."""

    candidate = Path(path)
    if not is_supported_audio_file(candidate):
        return None
    match = _STRICT_FLAT_AUDIO_PATTERN.match(candidate.stem)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group("title")).strip(" ._-\u2013\u2014")
    return title or None
