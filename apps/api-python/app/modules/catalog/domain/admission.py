"""Pure topology-v1 source-admission evidence and rejection contracts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    ProbedEntry,
    SidecarRole,
    SourceFormat,
    _validate_relative_path,
)

ARCHIVE_SOURCE_FORMATS = frozenset(
    {
        SourceFormat.EPUB,
        SourceFormat.CBZ,
        SourceFormat.CBR,
        SourceFormat.RAR,
        SourceFormat.ZIP,
    }
)
AUDIO_SOURCE_FORMATS = frozenset({SourceFormat.MP3, SourceFormat.M4A, SourceFormat.M4B})
DIRECT_FILE_SOURCE_FORMATS = frozenset(SourceFormat) - (
    ARCHIVE_SOURCE_FORMATS | AUDIO_SOURCE_FORMATS
)

# Topology v1 ignores only these exact NFC names. Hidden entries that are not
# listed here remain visible to admission and layout rules.
SYSTEM_NOISE_NAMES = frozenset(
    {
        "$RECYCLE.BIN",
        ".DS_Store",
        ".Spotlight-V100",
        ".Trashes",
        ".fseventsd",
        "System Volume Information",
        "Thumbs.db",
        "__MACOSX",
        "desktop.ini",
    }
)

_DISC_COMPONENT = re.compile(
    r"^(disc|cd|disk)[ _.-]?([1-9][0-9]*)$",
    flags=re.IGNORECASE | re.ASCII,
)


class AudioCodec(StrEnum):
    MPEG_LAYER_III = "MPEG_LAYER_III"
    AAC = "AAC"


class AdmissionRejectionReason(StrEnum):
    """Stable non-exception reasons for a completed negative observation."""

    UNSUPPORTED_EXTENSION = "UNSUPPORTED_EXTENSION"
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
    CORRUPT_SOURCE = "CORRUPT_SOURCE"
    ENCRYPTED_ARCHIVE = "ENCRYPTED_ARCHIVE"
    UNSAFE_ARCHIVE_PATH = "UNSAFE_ARCHIVE_PATH"
    PROBE_BUDGET_EXCEEDED = "PROBE_BUDGET_EXCEEDED"
    SYMLINK_NOT_ALLOWED = "SYMLINK_NOT_ALLOWED"
    JUNCTION_NOT_ALLOWED = "JUNCTION_NOT_ALLOWED"


def _require_integer(
    value: int,
    field_name: str,
    *,
    minimum: int = 0,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")


def _validate_byte_budget(bytes_examined: int, byte_budget: int) -> None:
    _require_integer(bytes_examined, "probe_bytes_examined", minimum=1)
    _require_integer(byte_budget, "probe_byte_budget", minimum=1)
    if bytes_examined > byte_budget:
        raise ValueError("probe bytes must not exceed the declared budget")


@dataclass(frozen=True, slots=True)
class DirectFileEvidence:
    """Bounded signature/text evidence for a non-container primary file."""

    source_format: SourceFormat
    probe_bytes_examined: int
    probe_byte_budget: int
    format_verified: bool = True

    def __post_init__(self) -> None:
        if self.source_format not in DIRECT_FILE_SOURCE_FORMATS:
            raise ValueError("direct evidence requires a direct-file source format")
        _validate_byte_budget(self.probe_bytes_examined, self.probe_byte_budget)
        if self.format_verified is not True:
            raise ValueError("accepted direct-file evidence must be verified")


@dataclass(frozen=True, slots=True)
class ArchiveEvidence:
    """Complete, bounded container facts needed to admit one archive."""

    source_format: SourceFormat
    entry_count: int
    inspected_entry_count: int
    entry_budget: int
    total_compressed_bytes: int
    total_uncompressed_bytes: int
    uncompressed_byte_budget: int
    compression_ratio_limit: int
    probe_bytes_examined: int
    probe_byte_budget: int
    image_entry_count: int = 0
    epub_mimetype_verified: bool = False
    epub_container_verified: bool = False
    comic_archive_verified: bool = False

    def __post_init__(self) -> None:
        if self.source_format not in ARCHIVE_SOURCE_FORMATS:
            raise ValueError("archive evidence requires an archive source format")
        _require_integer(self.entry_count, "entry_count", minimum=1)
        _require_integer(self.inspected_entry_count, "inspected_entry_count", minimum=1)
        _require_integer(self.entry_budget, "entry_budget", minimum=1)
        _require_integer(
            self.total_compressed_bytes, "total_compressed_bytes", minimum=1
        )
        _require_integer(
            self.total_uncompressed_bytes, "total_uncompressed_bytes", minimum=1
        )
        _require_integer(
            self.uncompressed_byte_budget, "uncompressed_byte_budget", minimum=1
        )
        _require_integer(
            self.compression_ratio_limit, "compression_ratio_limit", minimum=1
        )
        _require_integer(self.image_entry_count, "image_entry_count")
        if self.entry_count > self.entry_budget:
            raise ValueError("archive entries must not exceed the declared budget")
        if self.inspected_entry_count != self.entry_count:
            raise ValueError("accepted archive evidence must inspect every entry")
        if self.image_entry_count > self.entry_count:
            raise ValueError("image_entry_count cannot exceed entry_count")
        if self.total_uncompressed_bytes > self.uncompressed_byte_budget:
            raise ValueError(
                "archive uncompressed bytes must not exceed the declared budget"
            )
        if (
            self.total_uncompressed_bytes
            > self.total_compressed_bytes * self.compression_ratio_limit
        ):
            raise ValueError("archive compression ratio exceeds the declared limit")
        _validate_byte_budget(self.probe_bytes_examined, self.probe_byte_budget)
        for field_name, value in (
            ("epub_mimetype_verified", self.epub_mimetype_verified),
            ("epub_container_verified", self.epub_container_verified),
            ("comic_archive_verified", self.comic_archive_verified),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{field_name} must be a bool")

        if self.source_format is SourceFormat.EPUB:
            if not self.epub_mimetype_verified or not self.epub_container_verified:
                raise ValueError(
                    "EPUB evidence requires verified mimetype and container"
                )
            if self.comic_archive_verified:
                raise ValueError("EPUB evidence cannot be comic-archive evidence")
        elif (
            not self.comic_archive_verified
            or self.image_entry_count == 0
            or self.epub_mimetype_verified
            or self.epub_container_verified
        ):
            raise ValueError("comic archive evidence must prove image ownership")


@dataclass(frozen=True, slots=True)
class AudioEvidence:
    """Bounded audio-container and codec evidence for one original track."""

    source_format: SourceFormat
    codec: AudioCodec
    probe_bytes_examined: int
    probe_byte_budget: int
    container_verified: bool = True

    def __post_init__(self) -> None:
        if self.source_format not in AUDIO_SOURCE_FORMATS:
            raise ValueError("audio evidence requires an audio source format")
        if not isinstance(self.codec, AudioCodec):
            raise TypeError("codec must be an AudioCodec")
        expected_codec = (
            AudioCodec.MPEG_LAYER_III
            if self.source_format is SourceFormat.MP3
            else AudioCodec.AAC
        )
        if self.codec is not expected_codec:
            raise ValueError("audio codec does not match source format")
        _validate_byte_budget(self.probe_bytes_examined, self.probe_byte_budget)
        if self.container_verified is not True:
            raise ValueError("accepted audio evidence must verify its container")


@dataclass(frozen=True, slots=True)
class BundleEvidence:
    """Complete bounded ownership facts for one audio bundle directory."""

    entry_count: int
    audio_track_count: int
    disc_directory_count: int
    entry_budget: int
    complete: bool = True

    def __post_init__(self) -> None:
        _require_integer(self.entry_count, "entry_count", minimum=1)
        _require_integer(self.audio_track_count, "audio_track_count", minimum=1)
        _require_integer(self.disc_directory_count, "disc_directory_count")
        _require_integer(self.entry_budget, "entry_budget", minimum=1)
        if self.entry_count > self.entry_budget:
            raise ValueError("bundle entries must not exceed the declared budget")
        if self.entry_count < self.audio_track_count + self.disc_directory_count:
            raise ValueError("bundle entry_count does not cover its tracks and discs")
        if self.complete is not True:
            raise ValueError("accepted bundle evidence must be complete")


PrimaryEvidence: TypeAlias = DirectFileEvidence | ArchiveEvidence | AudioEvidence
AdmissionEvidence: TypeAlias = PrimaryEvidence | BundleEvidence


@dataclass(frozen=True, slots=True)
class SourceAdmissionEvidence:
    """A successful observation that maps losslessly to layout input."""

    relative_path: tuple[str, ...]
    entry_type: EntryType
    admission: AdmissionKind
    source_format: SourceFormat | None = None
    sidecar_role: SidecarRole | None = None
    evidence: AdmissionEvidence | None = None

    def __post_init__(self) -> None:
        if self.admission is AdmissionKind.UNSUPPORTED:
            raise ValueError("completed rejections use SourceAdmissionRejection")
        if self.entry_type in {EntryType.SYMLINK, EntryType.JUNCTION}:
            raise ValueError("links use SourceAdmissionRejection")

        entry = self.to_probed_entry()
        if entry.admission is AdmissionKind.PRIMARY:
            self._validate_primary_evidence()
        elif entry.admission is AdmissionKind.AUDIO_TRACK:
            if not isinstance(self.evidence, AudioEvidence):
                raise ValueError("audio tracks require AudioEvidence")
            if self.evidence.source_format is not entry.source_format:
                raise ValueError("audio evidence format does not match admission")
        elif entry.admission is AdmissionKind.SIDECAR:
            if self.evidence is not None:
                raise ValueError("sidecars carry only their typed role")
        elif self.evidence is not None and not (
            entry.entry_type is EntryType.DIRECTORY
            and isinstance(self.evidence, BundleEvidence)
        ):
            raise ValueError("ignored entries may only carry directory bundle evidence")

    def _validate_primary_evidence(self) -> None:
        source_format = self.source_format
        if source_format in ARCHIVE_SOURCE_FORMATS:
            if not isinstance(self.evidence, ArchiveEvidence):
                raise TypeError("primary archive admission requires ArchiveEvidence")
        elif source_format in DIRECT_FILE_SOURCE_FORMATS:
            if not isinstance(self.evidence, DirectFileEvidence):
                raise TypeError(
                    "primary direct-file admission requires DirectFileEvidence"
                )
        else:
            raise ValueError("PRIMARY admission cannot carry an audio source format")
        if self.evidence.source_format is not source_format:
            raise ValueError("primary evidence format does not match admission")

    def to_probed_entry(self) -> ProbedEntry:
        return ProbedEntry(
            relative_path=self.relative_path,
            entry_type=self.entry_type,
            admission=self.admission,
            source_format=self.source_format,
            sidecar_role=self.sidecar_role,
        )


@dataclass(frozen=True, slots=True)
class SourceAdmissionRejection:
    """A completed negative probe that scanning can record and continue past."""

    relative_path: tuple[str, ...]
    entry_type: EntryType
    reason: AdmissionRejectionReason

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path, "relative_path")
        if not isinstance(self.entry_type, EntryType):
            raise TypeError("entry_type must be an EntryType")
        if not isinstance(self.reason, AdmissionRejectionReason):
            raise TypeError("reason must be an AdmissionRejectionReason")
        if self.reason is AdmissionRejectionReason.SYMLINK_NOT_ALLOWED:
            if self.entry_type is not EntryType.SYMLINK:
                raise ValueError("symlink rejection requires a symlink entry")
        elif self.reason is AdmissionRejectionReason.JUNCTION_NOT_ALLOWED:
            if self.entry_type is not EntryType.JUNCTION:
                raise ValueError("junction rejection requires a junction entry")
        elif self.entry_type is not EntryType.FILE:
            raise ValueError("source-format rejections require a file entry")

    def to_probed_entry(self) -> ProbedEntry:
        ignored_link = self.entry_type in {EntryType.SYMLINK, EntryType.JUNCTION}
        return ProbedEntry(
            relative_path=self.relative_path,
            entry_type=self.entry_type,
            admission=(
                AdmissionKind.IGNORED if ignored_link else AdmissionKind.UNSUPPORTED
            ),
        )


SourceAdmissionResult: TypeAlias = SourceAdmissionEvidence | SourceAdmissionRejection


def parse_disc_component(name: str) -> int | None:
    """Parse the topology-v1 transparent-disc grammar without trimming."""

    if not isinstance(name, str):
        raise TypeError("disc component must be a string")
    match = _DISC_COMPONENT.fullmatch(unicodedata.normalize("NFC", name))
    return int(match.group(2)) if match is not None else None


def is_system_noise_name(name: str) -> bool:
    """Return whether one complete component is in the frozen exact allowlist."""

    if not isinstance(name, str):
        raise TypeError("system noise name must be a string")
    return unicodedata.normalize("NFC", name) in SYSTEM_NOISE_NAMES


__all__ = [
    "ARCHIVE_SOURCE_FORMATS",
    "AUDIO_SOURCE_FORMATS",
    "DIRECT_FILE_SOURCE_FORMATS",
    "SYSTEM_NOISE_NAMES",
    "AdmissionEvidence",
    "AdmissionRejectionReason",
    "ArchiveEvidence",
    "AudioCodec",
    "AudioEvidence",
    "BundleEvidence",
    "DirectFileEvidence",
    "PrimaryEvidence",
    "SourceAdmissionEvidence",
    "SourceAdmissionRejection",
    "SourceAdmissionResult",
    "is_system_noise_name",
    "parse_disc_component",
]
