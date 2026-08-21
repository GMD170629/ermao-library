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
class LayoutResource:
    source_key: str
    source_name: str
    assets: tuple[LayoutAsset, ...]


@dataclass(frozen=True, slots=True)
class LayoutBook:
    source_key: str
    source_name: str
    resources: tuple[LayoutResource, ...]


@dataclass(frozen=True, slots=True)
class LayoutViolation:
    code: LayoutViolationCode
    relative_path: str


@dataclass(frozen=True, slots=True)
class ParsedLayoutPath:
    """The only possible topology result for one admitted source file."""

    book: LayoutBook | None
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
            book=None,
            violations=(
                LayoutViolation(
                    code=LayoutViolationCode.INVALID_RELATIVE_PATH,
                    relative_path=relative_path,
                ),
            ),
        )
    canonical_path = unicodedata.normalize("NFC", physical_path)
    if organization_mode is LibraryOrganizationMode.FLAT:
        book = _single_file_book(physical_path, canonical_path)
    elif organization_mode is LibraryOrganizationMode.VOLUMES:
        book = _publication_book(physical_path, canonical_path)
    elif organization_mode is LibraryOrganizationMode.AUDIOBOOK:
        book = _audiobook_book(physical_path, canonical_path)
    else:
        raise ValueError(f"unsupported organization mode: {organization_mode}")
    return ParsedLayoutPath(book=book)


def is_audiobook_disc_directory(name: str) -> bool:
    """Return whether a directory is a transparent audiobook disc grouping."""

    return bool(_DISC_DIRECTORY_PATTERN.fullmatch(unicodedata.normalize("NFC", name)))


def _single_file_book(physical_path: str, canonical_path: str) -> LayoutBook:
    source_name = _file_stem(physical_path)
    resource = _single_asset_resource(
        source_key=_resource_key(canonical_path),
        source_name=source_name,
        physical_path=physical_path,
    )
    return LayoutBook(
        source_key=_book_key(canonical_path),
        source_name=source_name,
        resources=(resource,),
    )


def _publication_book(physical_path: str, canonical_path: str) -> LayoutBook:
    physical_parts = physical_path.split("/")
    canonical_parts = canonical_path.split("/")
    if len(physical_parts) == 1:
        return _single_file_book(physical_path, canonical_path)

    book_path = canonical_parts[0]
    book_name = physical_parts[0]
    resource = _single_asset_resource(
        source_key=_resource_key(canonical_path),
        source_name=_file_stem(physical_path),
        physical_path=physical_path,
    )
    return LayoutBook(
        source_key=_book_key(book_path),
        source_name=book_name,
        resources=(resource,),
    )


def _audiobook_book(physical_path: str, canonical_path: str) -> LayoutBook:
    physical_parts = physical_path.split("/")
    canonical_parts = canonical_path.split("/")
    if len(physical_parts) == 1:
        return _single_file_book(physical_path, canonical_path)

    book_name = physical_parts[0]
    book_path = canonical_parts[0]
    semantic_directories = [
        (physical, canonical)
        for physical, canonical in zip(
            physical_parts[1:-1], canonical_parts[1:-1], strict=True
        )
        if not is_audiobook_disc_directory(physical)
    ]
    resource_path = "/".join(
        [
            canonical_parts[0],
            *(canonical for _physical, canonical in semantic_directories),
        ]
    )
    resource_name = semantic_directories[-1][0] if semantic_directories else book_name
    return LayoutBook(
        source_key=_book_key(book_path),
        source_name=book_name,
        resources=(
            _single_asset_resource(
                source_key=_resource_key(resource_path),
                source_name=resource_name,
                physical_path=physical_path,
            ),
        ),
    )


def _single_asset_resource(
    *, source_key: str, source_name: str, physical_path: str
) -> LayoutResource:
    return LayoutResource(
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


def _book_key(path: str) -> str:
    return f"book:{path}"


def _resource_key(path: str) -> str:
    return f"resource:{path}"
