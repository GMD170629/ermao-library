"""Framework-independent audiobook metadata contracts and constants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

LEGACY_AUDIO_EXTS = frozenset({".m4b", ".m4a", ".mp3"})
SUPPORTED_AUDIO_EXTS = frozenset(
    {
        ".aac",
        ".ac3",
        ".adx",
        ".aif",
        ".aifc",
        ".aiff",
        ".amr",
        ".ape",
        ".aptx",
        ".aptxhd",
        ".au",
        ".caf",
        ".dff",
        ".dsf",
        ".dts",
        ".eac3",
        ".flac",
        ".g722",
        ".g726",
        ".gsm",
        ".lbc",
        ".m4a",
        ".m4b",
        ".m4r",
        ".mka",
        ".mlp",
        ".mp2",
        ".mp3",
        ".mpc",
        ".oga",
        ".ogg",
        ".oma",
        ".opus",
        ".qcp",
        ".ra",
        ".rf64",
        ".shn",
        ".snd",
        ".sph",
        ".spx",
        ".tak",
        ".thd",
        ".tta",
        ".voc",
        ".w64",
        ".wav",
        ".wave",
        ".weba",
        ".wma",
        ".wv",
        ".xma",
    }
)
NEW_AUDIO_EXTS = SUPPORTED_AUDIO_EXTS - LEGACY_AUDIO_EXTS

_AUDIO_MIME_TYPES = {
    ".aac": "audio/aac",
    ".ac3": "audio/ac3",
    ".aif": "audio/aiff",
    ".aifc": "audio/aiff",
    ".aiff": "audio/aiff",
    ".amr": "audio/amr",
    ".au": "audio/basic",
    ".dts": "audio/vnd.dts",
    ".eac3": "audio/eac3",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".m4r": "audio/mp4",
    ".mka": "audio/x-matroska",
    ".mp2": "audio/mpeg",
    ".mp3": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".ra": "audio/vnd.rn-realaudio",
    ".rf64": "audio/wav",
    ".snd": "audio/basic",
    ".spx": "audio/ogg",
    ".w64": "audio/wav",
    ".wav": "audio/wav",
    ".wave": "audio/wav",
    ".weba": "audio/webm",
    ".wma": "audio/x-ms-wma",
}
MAX_AUDIO_CHAPTERS = 10_000
MAX_AUDIO_BUNDLE_TRACKS = 10_000
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
    return _AUDIO_MIME_TYPES.get(
        extension,
        f"audio/x-{extension.removeprefix('.')}"
        if extension in SUPPORTED_AUDIO_EXTS
        else "application/octet-stream",
    )


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
