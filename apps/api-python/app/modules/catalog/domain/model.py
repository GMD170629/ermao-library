"""Small immutable contracts used by the pure catalog layout interpreter."""

from dataclasses import dataclass
from enum import StrEnum


class OrganizationMode(StrEnum):
    FLAT = "FLAT"
    VOLUMES = "VOLUMES"
    AUDIOBOOK = "AUDIOBOOK"


class EntryType(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    SYMLINK = "SYMLINK"
    JUNCTION = "JUNCTION"


class AdmissionKind(StrEnum):
    PRIMARY = "PRIMARY"
    AUDIO_TRACK = "AUDIO_TRACK"
    SIDECAR = "SIDECAR"
    UNSUPPORTED = "UNSUPPORTED"
    IGNORED = "IGNORED"


class SourceFormat(StrEnum):
    EPUB = "EPUB"
    MOBI = "MOBI"
    AZW = "AZW"
    AZW3 = "AZW3"
    PRC = "PRC"
    TXT = "TXT"
    PDF = "PDF"
    CBZ = "CBZ"
    CBR = "CBR"
    RAR = "RAR"
    ZIP = "ZIP"
    MP3 = "MP3"
    M4A = "M4A"
    M4B = "M4B"


class SidecarRole(StrEnum):
    OPF = "OPF"
    ARTWORK = "ARTWORK"
    LYRICS = "LYRICS"
    CUE = "CUE"


_AUDIO_SOURCE_FORMATS = frozenset(
    {SourceFormat.MP3, SourceFormat.M4A, SourceFormat.M4B}
)


class PathComparison(StrEnum):
    SENSITIVE = "SENSITIVE"
    INSENSITIVE = "INSENSITIVE"


class SourceKind(StrEnum):
    SINGLE_FILE = "SINGLE_FILE"
    MULTI_ASSET_AUDIO = "MULTI_ASSET_AUDIO"


class ViolationCode(StrEnum):
    PATH_NORMALIZATION_COLLISION = "PATH_NORMALIZATION_COLLISION"
    FLAT_NESTING_NOT_ALLOWED = "FLAT_NESTING_NOT_ALLOWED"
    VERSION_DIRECTORY_REQUIRED = "VERSION_DIRECTORY_REQUIRED"
    BUNDLE_LAYOUT_AMBIGUOUS = "BUNDLE_LAYOUT_AMBIGUOUS"
    AUDIO_LAYOUT_MIXED = "AUDIO_LAYOUT_MIXED"
    AUDIO_DEPTH_EXCEEDED = "AUDIO_DEPTH_EXCEEDED"
    AUDIO_NON_AUDIO_RESOURCE = "AUDIO_NON_AUDIO_RESOURCE"
    AUDIO_TRACK_LIMIT_EXCEEDED = "AUDIO_TRACK_LIMIT_EXCEEDED"
    SYMLINK_NOT_ALLOWED = "SYMLINK_NOT_ALLOWED"


def _validate_relative_path(path: tuple[str, ...], field_name: str) -> None:
    if not isinstance(path, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not path:
        raise ValueError(f"{field_name} must be a non-empty tuple")
    for component in path:
        if not isinstance(component, str):
            raise TypeError(f"{field_name} components must be strings")
        if not component:
            raise ValueError(f"{field_name} components must be non-empty strings")
        if "/" in component or "\\" in component:
            raise ValueError(f"{field_name} components must not contain separators")
        if component in {".", ".."} or "\x00" in component:
            raise ValueError(f"{field_name} contains an invalid component")


def _is_strict_descendant(path: tuple[str, ...], ancestor: tuple[str, ...]) -> bool:
    return len(path) > len(ancestor) and path[: len(ancestor)] == ancestor


def _is_direct_child(path: tuple[str, ...], parent: tuple[str, ...]) -> bool:
    return len(path) == len(parent) + 1 and path[: len(parent)] == parent


@dataclass(frozen=True, slots=True)
class ProbedEntry:
    """A filesystem observation after the admission boundary has run.

    The domain deliberately receives relative path components only. Filesystem
    identity, timestamps, sizes and parser objects belong to infrastructure.
    """

    relative_path: tuple[str, ...]
    entry_type: EntryType
    admission: AdmissionKind
    source_format: SourceFormat | None = None
    sidecar_role: SidecarRole | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_type, EntryType):
            raise TypeError("entry_type must be an EntryType")
        if not isinstance(self.admission, AdmissionKind):
            raise TypeError("admission must be an AdmissionKind")
        _validate_relative_path(self.relative_path, "relative_path")

        if self.source_format is not None and not isinstance(
            self.source_format, SourceFormat
        ):
            raise TypeError("source_format must be a SourceFormat")
        if self.sidecar_role is not None and not isinstance(
            self.sidecar_role, SidecarRole
        ):
            raise TypeError("sidecar_role must be a SidecarRole")

        if self.entry_type in {EntryType.SYMLINK, EntryType.JUNCTION}:
            if self.source_format is not None or self.sidecar_role is not None:
                raise ValueError("links cannot carry format or sidecar evidence")
            if self.admission is not AdmissionKind.IGNORED:
                raise ValueError("links must be ignored by source admission")

        if self.admission is AdmissionKind.SIDECAR:
            if (
                self.entry_type is not EntryType.FILE
                or self.sidecar_role is None
                or self.source_format is not None
            ):
                raise ValueError("sidecars must be files with a sidecar_role")
        elif self.sidecar_role is not None:
            raise ValueError("only sidecars may carry sidecar_role")

        if self.admission in {AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK}:
            if self.entry_type is not EntryType.FILE:
                raise ValueError("primary admissions must be files")
            if self.source_format is None:
                raise ValueError("primary admissions require source_format")
            if (
                self.admission is AdmissionKind.AUDIO_TRACK
                and self.source_format not in _AUDIO_SOURCE_FORMATS
            ):
                raise ValueError("audio admissions require an audio source format")
            if (
                self.admission is AdmissionKind.PRIMARY
                and self.source_format in _AUDIO_SOURCE_FORMATS
            ):
                raise ValueError("audio source formats require AUDIO_TRACK admission")
        elif self.source_format is not None:
            raise ValueError("only primary admissions may carry source_format")


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    path: tuple[str, ...]
    source_format: SourceFormat
    order: int
    disc_number: int = 0

    def __post_init__(self) -> None:
        _validate_relative_path(self.path, "path")
        if not isinstance(self.source_format, SourceFormat):
            raise TypeError("source_format must be a SourceFormat")
        if isinstance(self.order, bool) or not isinstance(self.order, int):
            raise TypeError("order must be an integer")
        if self.order < 0:
            raise ValueError("order must be a non-negative integer")
        if isinstance(self.disc_number, bool) or not isinstance(self.disc_number, int):
            raise TypeError("disc_number must be an integer")
        if self.disc_number < 0:
            raise ValueError("disc_number must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class VolumeCandidate:
    work_path: tuple[str, ...]
    version_path: tuple[str, ...] | None
    volume_path: tuple[str, ...]
    source_kind: SourceKind
    assets: tuple[AssetCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, SourceKind):
            raise TypeError("source_kind must be a SourceKind")
        _validate_relative_path(self.work_path, "work_path")
        if self.version_path is not None:
            _validate_relative_path(self.version_path, "version_path")
        _validate_relative_path(self.volume_path, "volume_path")
        if self.version_path is not None:
            if not _is_direct_child(self.version_path, self.work_path):
                raise ValueError("version_path must be a direct child of work_path")
            if not _is_direct_child(self.volume_path, self.version_path):
                raise ValueError("volume_path must be a direct child of version_path")
        elif self.volume_path != self.work_path and not _is_direct_child(
            self.volume_path, self.work_path
        ):
            raise ValueError("volume_path must equal or be a direct child of work_path")
        if not isinstance(self.assets, tuple):
            raise TypeError("assets must be a tuple")
        if not self.assets:
            raise ValueError("assets must be a non-empty tuple")
        if any(not isinstance(asset, AssetCandidate) for asset in self.assets):
            raise TypeError("assets must contain AssetCandidate values")
        if tuple(asset.order for asset in self.assets) != tuple(
            range(len(self.assets))
        ):
            raise ValueError("assets order must be continuous from zero")
        if self.source_kind is SourceKind.SINGLE_FILE and len(self.assets) != 1:
            raise ValueError("single-file volumes require one asset")
        if self.source_kind is SourceKind.SINGLE_FILE:
            if self.assets[0].path != self.volume_path:
                raise ValueError("single-file asset must equal volume_path")
        elif any(
            not _is_strict_descendant(asset.path, self.volume_path)
            for asset in self.assets
        ):
            raise ValueError("multi-asset files must be under volume_path")


@dataclass(frozen=True, slots=True)
class LayoutViolation:
    code: ViolationCode
    unit_path: tuple[str, ...]
    related_paths: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, ViolationCode):
            raise TypeError("code must be a ViolationCode")
        _validate_relative_path(self.unit_path, "unit_path")
        if not isinstance(self.related_paths, tuple):
            raise TypeError("related_paths must be a tuple")
        for path in self.related_paths:
            _validate_relative_path(path, "related_paths path")


@dataclass(frozen=True, slots=True)
class LayoutResult:
    candidates: tuple[VolumeCandidate, ...]
    violations: tuple[LayoutViolation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple")
        if not isinstance(self.violations, tuple):
            raise TypeError("violations must be a tuple")
        if any(
            not isinstance(candidate, VolumeCandidate) for candidate in self.candidates
        ):
            raise TypeError("candidates must contain VolumeCandidate values")
        if any(
            not isinstance(violation, LayoutViolation) for violation in self.violations
        ):
            raise TypeError("violations must contain LayoutViolation values")
