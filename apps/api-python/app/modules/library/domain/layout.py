"""Deterministically map one library-relative file path to library topology."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath


class LibraryOrganizationMode(str, Enum):
    FLAT = "FLAT"
    VOLUMES = "VOLUMES"
    AUDIOBOOK = "AUDIOBOOK"


class LayoutViolationCode(str, Enum):
    INVALID_RELATIVE_PATH = "INVALID_RELATIVE_PATH"


@dataclass(frozen=True, slots=True)
class LayoutAsset:
    relative_path: str
    order: int


@dataclass(frozen=True, slots=True)
class LayoutVolume:
    source_key: str
    source_name: str
    assets: tuple[LayoutAsset, ...]


@dataclass(frozen=True, slots=True)
class LayoutVersion:
    source_key: str
    source_name: str | None
    volumes: tuple[LayoutVolume, ...]


@dataclass(frozen=True, slots=True)
class LayoutWork:
    source_key: str
    source_name: str
    versions: tuple[LayoutVersion, ...]


@dataclass(frozen=True, slots=True)
class LayoutViolation:
    code: LayoutViolationCode
    relative_path: str


@dataclass(frozen=True, slots=True)
class ParsedLayoutPath:
    """The only possible topology result for one admitted source file."""

    work: LayoutWork | None
    violations: tuple[LayoutViolation, ...] = ()


_DRIVE_PREFIX_LENGTH = 2
_DISC_DIRECTORY_PATTERN = re.compile(
    r"^(?:cd|disc|disk|\u789f|\u76d8)"
    r"(?:\s*[-_. ]*\d+(?:\s*(?:of|/|[-\u2013\u2014])\s*\d+)?)?$",
    re.IGNORECASE,
)


def parse_library_file_path(
    relative_path: str,
    organization_mode: LibraryOrganizationMode,
) -> ParsedLayoutPath:
    """Parse one path without consulting the filesystem, siblings, or metadata."""

    physical_path = _logical_relative_path(relative_path)
    if physical_path is None:
        return ParsedLayoutPath(
            work=None,
            violations=(
                LayoutViolation(
                    code=LayoutViolationCode.INVALID_RELATIVE_PATH,
                    relative_path=relative_path,
                ),
            ),
        )
    canonical_path = unicodedata.normalize("NFC", physical_path)
    if organization_mode is LibraryOrganizationMode.FLAT:
        work = _single_file_work(physical_path, canonical_path)
    elif organization_mode is LibraryOrganizationMode.VOLUMES:
        work = _publication_work(physical_path, canonical_path)
    elif organization_mode is LibraryOrganizationMode.AUDIOBOOK:
        work = _audiobook_work(physical_path, canonical_path)
    else:
        raise ValueError(f"unsupported organization mode: {organization_mode}")
    return ParsedLayoutPath(work=work)


def is_audiobook_disc_directory(name: str) -> bool:
    """Return whether a directory is a transparent audiobook disc grouping."""

    return bool(_DISC_DIRECTORY_PATTERN.fullmatch(unicodedata.normalize("NFC", name)))


def _single_file_work(physical_path: str, canonical_path: str) -> LayoutWork:
    source_name = _file_stem(physical_path)
    volume = _single_asset_volume(
        source_key=_volume_key(canonical_path),
        source_name=source_name,
        physical_path=physical_path,
    )
    return LayoutWork(
        source_key=_work_key(canonical_path),
        source_name=source_name,
        versions=(
            LayoutVersion(
                source_key=_version_key(canonical_path),
                source_name=None,
                volumes=(volume,),
            ),
        ),
    )


def _publication_work(physical_path: str, canonical_path: str) -> LayoutWork:
    physical_parts = physical_path.split("/")
    canonical_parts = canonical_path.split("/")
    if len(physical_parts) == 1:
        return _single_file_work(physical_path, canonical_path)

    work_path = canonical_parts[0]
    work_name = physical_parts[0]
    if len(physical_parts) >= 3:
        version_path = "/".join(canonical_parts[:2])
        version_name: str | None = physical_parts[1]
    else:
        version_path = work_path
        version_name = None
    volume = _single_asset_volume(
        source_key=_volume_key(canonical_path),
        source_name=_file_stem(physical_path),
        physical_path=physical_path,
    )
    return LayoutWork(
        source_key=_work_key(work_path),
        source_name=work_name,
        versions=(
            LayoutVersion(
                source_key=_version_key(version_path),
                source_name=version_name,
                volumes=(volume,),
            ),
        ),
    )


def _audiobook_work(physical_path: str, canonical_path: str) -> LayoutWork:
    physical_parts = physical_path.split("/")
    canonical_parts = canonical_path.split("/")
    if len(physical_parts) == 1:
        return _single_file_work(physical_path, canonical_path)

    work_name = physical_parts[0]
    work_path = canonical_parts[0]
    semantic_directories = [
        (physical, canonical)
        for physical, canonical in zip(
            physical_parts[1:-1], canonical_parts[1:-1], strict=True
        )
        if not is_audiobook_disc_directory(physical)
    ]
    version = semantic_directories[0] if semantic_directories else None
    volume = semantic_directories[1] if len(semantic_directories) >= 2 else None
    version_path = (
        f"{work_path}/{version[1]}" if version is not None else work_path
    )
    volume_path = (
        f"{version_path}/{volume[1]}" if volume is not None else version_path
    )
    volume_name = (
        volume[0]
        if volume is not None
        else version[0]
        if version is not None
        else work_name
    )
    return LayoutWork(
        source_key=_work_key(work_path),
        source_name=work_name,
        versions=(
            LayoutVersion(
                source_key=_version_key(version_path),
                source_name=version[0] if version is not None else None,
                volumes=(
                    _single_asset_volume(
                        source_key=_volume_key(volume_path),
                        source_name=volume_name,
                        physical_path=physical_path,
                    ),
                ),
            ),
        ),
    )


def _single_asset_volume(
    *, source_key: str, source_name: str, physical_path: str
) -> LayoutVolume:
    return LayoutVolume(
        source_key=source_key,
        source_name=source_name,
        assets=(LayoutAsset(relative_path=physical_path, order=0),),
    )


def _logical_relative_path(relative_path: str) -> str | None:
    if "\x00" in relative_path:
        return None
    physical = relative_path.replace("\\", "/")
    if not physical or physical.startswith("/"):
        return None
    if _has_windows_drive_prefix(physical):
        return None
    if physical.endswith("/"):
        return None
    parts = physical.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _file_stem(path: str) -> str:
    return PurePosixPath(path.rsplit("/", 1)[-1]).stem


def _has_windows_drive_prefix(path: str) -> bool:
    return (
        len(path) >= _DRIVE_PREFIX_LENGTH
        and path[0].isascii()
        and path[0].isalpha()
        and path[1] == ":"
    )


def _work_key(path: str) -> str:
    return f"work:{path}"


def _version_key(path: str) -> str:
    return f"version:{path}"


def _volume_key(path: str) -> str:
    return f"volume:{path}"
