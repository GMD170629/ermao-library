"""Interpret classified directory entries as Work / Version / Volume / Asset."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from app.modules.library.domain.layout_ordering import natural_sort_key


class LibraryOrganizationMode(str, Enum):
    FLAT = "FLAT"
    VOLUMES = "VOLUMES"
    AUDIOBOOK = "AUDIOBOOK"


class LayoutEntryType(str, Enum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class LayoutSourceType(str, Enum):
    PUBLICATION = "PUBLICATION"
    AUDIO = "AUDIO"
    SIDECAR = "SIDECAR"
    UNSUPPORTED = "UNSUPPORTED"


class LayoutViolationCode(str, Enum):
    INVALID_RELATIVE_PATH = "INVALID_RELATIVE_PATH"
    NORMALIZED_PATH_COLLISION = "NORMALIZED_PATH_COLLISION"
    FLAT_NESTING_NOT_ALLOWED = "FLAT_NESTING_NOT_ALLOWED"
    VERSION_DIRECTORY_REQUIRED = "VERSION_DIRECTORY_REQUIRED"
    VOLUME_NESTING_NOT_ALLOWED = "VOLUME_NESTING_NOT_ALLOWED"
    AUDIO_MIXED_LAYOUT = "AUDIO_MIXED_LAYOUT"
    AUDIO_INVALID_NESTING = "AUDIO_INVALID_NESTING"


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    relative_path: str
    entry_type: LayoutEntryType
    source_type: LayoutSourceType


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
class LayoutResult:
    works: tuple[LayoutWork, ...]
    violations: tuple[LayoutViolation, ...]


@dataclass(frozen=True, slots=True)
class _NormalizedEntry:
    physical_path: str
    canonical_path: str
    entry_type: LayoutEntryType
    source_type: LayoutSourceType


@dataclass(frozen=True, slots=True)
class _LayoutIndex:
    files: dict[str, _NormalizedEntry]
    directories: frozenset[str]
    children: dict[str, tuple[str, ...]]
    directory_physical: dict[str, str]


_ROOT = ""
_DRIVE_PREFIX_LENGTH = 2


def interpret_library_layout(
    entries: Iterable[LayoutEntry],
    organization_mode: LibraryOrganizationMode,
) -> LayoutResult:
    """Interpret already classified entries. Does not read the filesystem."""

    normalized_entries, violations = _normalize_entries(entries)
    index = _build_index(normalized_entries)
    if organization_mode is LibraryOrganizationMode.FLAT:
        works, structural = _interpret_flat(index)
    elif organization_mode is LibraryOrganizationMode.VOLUMES:
        works, structural = _interpret_volumes(index)
    elif organization_mode is LibraryOrganizationMode.AUDIOBOOK:
        works, structural = _interpret_audiobook(index)
    else:
        raise ValueError(f"unsupported organization mode: {organization_mode}")
    violations.extend(structural)
    return LayoutResult(
        works=_sort_works(works),
        violations=_sort_violations(violations),
    )


def _logical_relative_path(relative_path: str) -> str | None:
    """Return a slash-normalized physical relative path, preserving Unicode spelling."""

    if "\x00" in relative_path:
        return None
    physical = relative_path.replace("\\", "/")
    if not physical or physical.startswith("/"):
        return None
    if _has_windows_drive_prefix(physical):
        return None
    if physical.endswith("/"):
        physical = physical.rstrip("/")
        if not physical:
            return None
    parts = physical.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _canonical_path(physical_path: str) -> str:
    return unicodedata.normalize("NFC", physical_path)


def _normalize_entries(
    entries: Iterable[LayoutEntry],
) -> tuple[list[_NormalizedEntry], list[LayoutViolation]]:
    violations: list[LayoutViolation] = []
    grouped: dict[str, list[_NormalizedEntry]] = {}
    valid: list[_NormalizedEntry] = []
    for entry in entries:
        physical = _logical_relative_path(entry.relative_path)
        if physical is None:
            violations.append(
                LayoutViolation(
                    code=LayoutViolationCode.INVALID_RELATIVE_PATH,
                    relative_path=entry.relative_path,
                )
            )
            continue
        normalized = _NormalizedEntry(
            physical_path=physical,
            canonical_path=_canonical_path(physical),
            entry_type=entry.entry_type,
            source_type=entry.source_type,
        )
        valid.append(normalized)
        grouped.setdefault(normalized.canonical_path, []).append(normalized)

    for group in grouped.values():
        physicals = {item.physical_path for item in group}
        if len(physicals) > 1:
            violations.extend(
                LayoutViolation(
                    code=LayoutViolationCode.NORMALIZED_PATH_COLLISION,
                    relative_path=physical,
                )
                for physical in physicals
            )

    directory_spellings = _directory_spellings(valid)
    colliding_directories = {
        canonical
        for canonical, physicals in directory_spellings.items()
        if len(physicals) > 1
    }
    for physicals in directory_spellings.values():
        if len(physicals) > 1:
            violations.extend(
                LayoutViolation(
                    code=LayoutViolationCode.NORMALIZED_PATH_COLLISION,
                    relative_path=physical,
                )
                for physical in physicals
            )

    kept = [
        group[0]
        for group in grouped.values()
        if len({item.physical_path for item in group}) == 1
        and not _is_under_directories(group[0].canonical_path, colliding_directories)
    ]
    return kept, violations


def _build_index(entries: Sequence[_NormalizedEntry]) -> _LayoutIndex:
    files: dict[str, _NormalizedEntry] = {}
    directories: set[str] = set()
    children: dict[str, set[str]] = {}
    directory_physical: dict[str, str] = {}
    for entry in entries:
        if entry.entry_type is LayoutEntryType.DIRECTORY:
            _register_ancestors(
                entry.canonical_path,
                entry.physical_path,
                directories,
                children,
                directory_physical,
            )
            continue
        files[entry.canonical_path] = entry
        parent_canonical = _parent_path(entry.canonical_path)
        parent_physical = _parent_path(entry.physical_path)
        if parent_canonical:
            _register_ancestors(
                parent_canonical,
                parent_physical,
                directories,
                children,
                directory_physical,
            )
        _add_child(children, parent_canonical, entry.canonical_path)
    return _LayoutIndex(
        files=files,
        directories=frozenset(directories),
        children={
            parent: tuple(_sort_paths(child_paths))
            for parent, child_paths in children.items()
        },
        directory_physical=directory_physical,
    )


def _interpret_flat(
    index: _LayoutIndex,
) -> tuple[list[LayoutWork], list[LayoutViolation]]:
    works: list[LayoutWork] = []
    violations: list[LayoutViolation] = []
    nested_roots: set[str] = set()
    for directory in index.directories:
        nested_roots.add(_root_segment(directory))
    for path in index.files:
        if "/" in path:
            nested_roots.add(_root_segment(path))
    for nested_root in nested_roots:
        violations.append(
            LayoutViolation(
                code=LayoutViolationCode.FLAT_NESTING_NOT_ALLOWED,
                relative_path=nested_root,
            )
        )
    for path, entry in index.files.items():
        if "/" in path or entry.source_type is not LayoutSourceType.PUBLICATION:
            continue
        works.append(_single_file_work(entry))
    return works, violations


def _interpret_volumes(
    index: _LayoutIndex,
) -> tuple[list[LayoutWork], list[LayoutViolation]]:
    works: list[LayoutWork] = []
    violations: list[LayoutViolation] = []
    for path, entry in index.files.items():
        if entry.source_type is not LayoutSourceType.PUBLICATION:
            continue
        segments = path.count("/") + 1
        if segments < 3:
            violations.append(
                LayoutViolation(
                    code=LayoutViolationCode.VERSION_DIRECTORY_REQUIRED,
                    relative_path=entry.physical_path,
                )
            )
            continue
        if segments > 3:
            violations.append(
                LayoutViolation(
                    code=LayoutViolationCode.VOLUME_NESTING_NOT_ALLOWED,
                    relative_path=entry.physical_path,
                )
            )
    for work_path in _child_directories(index, _ROOT):
        versions: list[LayoutVersion] = []
        for version_path in _child_directories(index, work_path):
            volumes = [
                _publication_volume(index.files[file_path])
                for file_path in _child_files(index, version_path)
                if index.files[file_path].source_type is LayoutSourceType.PUBLICATION
            ]
            if not volumes:
                continue
            versions.append(
                LayoutVersion(
                    source_key=_version_key(version_path),
                    source_name=_directory_name(index, version_path),
                    volumes=_sort_volumes(volumes),
                )
            )
        if not versions:
            continue
        works.append(
            LayoutWork(
                source_key=_work_key(work_path),
                source_name=_directory_name(index, work_path),
                versions=_sort_versions(versions),
            )
        )
    return works, violations


def _interpret_audiobook(
    index: _LayoutIndex,
) -> tuple[list[LayoutWork], list[LayoutViolation]]:
    works: list[LayoutWork] = []
    violations: list[LayoutViolation] = []
    for path, entry in index.files.items():
        if "/" in path or entry.source_type is not LayoutSourceType.AUDIO:
            continue
        works.append(_single_file_work(entry))
    for work_path in _child_directories(index, _ROOT):
        work, structural = _interpret_audiobook_work(index, work_path)
        violations.extend(structural)
        if work is not None:
            works.append(work)
    return works, violations


def _interpret_audiobook_work(
    index: _LayoutIndex,
    work_path: str,
) -> tuple[LayoutWork | None, list[LayoutViolation]]:
    violations: list[LayoutViolation] = []
    direct_tracks = _audio_files(index, work_path)
    volume_directories = [
        directory
        for directory in _child_directories(index, work_path)
        if _has_audio_descendant(index, directory)
    ]
    if direct_tracks and volume_directories:
        return (
            None,
            [
                LayoutViolation(
                    code=LayoutViolationCode.AUDIO_MIXED_LAYOUT,
                    relative_path=index.directory_physical.get(work_path, work_path),
                )
            ],
        )
    if direct_tracks:
        volume = LayoutVolume(
            source_key=_volume_key(work_path),
            source_name=_directory_name(index, work_path),
            assets=_assets_for(index, direct_tracks),
        )
        return _work_with_implicit_version(index, work_path, (volume,)), violations
    volumes: list[LayoutVolume] = []
    for volume_path in volume_directories:
        interpreted, nested = _interpret_audiobook_volume(index, volume_path)
        violations.extend(nested)
        if interpreted is not None:
            volumes.append(interpreted)
    if not volumes:
        return None, violations
    return _work_with_implicit_version(
        index,
        work_path,
        _sort_volumes(volumes),
    ), violations


def _interpret_audiobook_volume(
    index: _LayoutIndex,
    volume_path: str,
) -> tuple[LayoutVolume | None, list[LayoutViolation]]:
    nested = [
        descendant
        for descendant in _descendant_directories(index, volume_path)
        if _has_audio_descendant(index, descendant)
    ]
    if nested:
        return None, [
            LayoutViolation(
                code=LayoutViolationCode.AUDIO_INVALID_NESTING,
                relative_path=index.directory_physical.get(descendant, descendant),
            )
            for descendant in nested
        ]
    tracks = _audio_files(index, volume_path)
    if not tracks:
        return None, []
    return (
        LayoutVolume(
            source_key=_volume_key(volume_path),
            source_name=_directory_name(index, volume_path),
            assets=_assets_for(index, tracks),
        ),
        [],
    )


def _single_file_work(entry: _NormalizedEntry) -> LayoutWork:
    source_name = _file_stem(entry.physical_path)
    volume = LayoutVolume(
        source_key=_volume_key(entry.canonical_path),
        source_name=source_name,
        assets=(LayoutAsset(relative_path=entry.physical_path, order=0),),
    )
    return LayoutWork(
        source_key=_work_key(entry.canonical_path),
        source_name=source_name,
        versions=(
            LayoutVersion(
                source_key=_version_key(entry.canonical_path),
                source_name=None,
                volumes=(volume,),
            ),
        ),
    )


def _work_with_implicit_version(
    index: _LayoutIndex,
    work_path: str,
    volumes: tuple[LayoutVolume, ...],
) -> LayoutWork:
    return LayoutWork(
        source_key=_work_key(work_path),
        source_name=_directory_name(index, work_path),
        versions=(
            LayoutVersion(
                source_key=_version_key(work_path),
                source_name=None,
                volumes=volumes,
            ),
        ),
    )


def _publication_volume(entry: _NormalizedEntry) -> LayoutVolume:
    return LayoutVolume(
        source_key=_volume_key(entry.canonical_path),
        source_name=_file_stem(entry.physical_path),
        assets=(LayoutAsset(relative_path=entry.physical_path, order=0),),
    )


def _assets_for(
    index: _LayoutIndex,
    canonical_paths: Sequence[str],
) -> tuple[LayoutAsset, ...]:
    ordered = _sort_paths(canonical_paths)
    return tuple(
        LayoutAsset(
            relative_path=index.files[path].physical_path,
            order=order,
        )
        for order, path in enumerate(ordered)
    )


def _sort_works(works: Sequence[LayoutWork]) -> tuple[LayoutWork, ...]:
    return tuple(
        sorted(
            works,
            key=lambda work: (natural_sort_key(work.source_name), work.source_key),
        )
    )


def _sort_versions(versions: Sequence[LayoutVersion]) -> tuple[LayoutVersion, ...]:
    return tuple(
        sorted(
            versions,
            key=lambda version: (
                natural_sort_key(version.source_name or ""),
                version.source_key,
            ),
        )
    )


def _sort_volumes(volumes: Sequence[LayoutVolume]) -> tuple[LayoutVolume, ...]:
    return tuple(
        sorted(
            volumes,
            key=lambda volume: (
                natural_sort_key(volume.source_name),
                volume.source_key,
            ),
        )
    )


def _sort_violations(
    violations: Sequence[LayoutViolation],
) -> tuple[LayoutViolation, ...]:
    unique = {
        (violation.code, violation.relative_path): violation for violation in violations
    }
    return tuple(
        sorted(
            unique.values(),
            key=lambda violation: (violation.code.value, violation.relative_path),
        )
    )


def _sort_paths(paths: Iterable[str]) -> list[str]:
    return sorted(
        paths,
        key=lambda path: (natural_sort_key(_entry_name(path)), path),
    )


def _child_directories(index: _LayoutIndex, parent: str) -> tuple[str, ...]:
    return tuple(
        path for path in index.children.get(parent, ()) if path in index.directories
    )


def _child_files(index: _LayoutIndex, parent: str) -> tuple[str, ...]:
    return tuple(path for path in index.children.get(parent, ()) if path in index.files)


def _audio_files(index: _LayoutIndex, parent: str) -> tuple[str, ...]:
    return tuple(
        path
        for path in _child_files(index, parent)
        if index.files[path].source_type is LayoutSourceType.AUDIO
    )


def _has_audio_descendant(index: _LayoutIndex, directory: str) -> bool:
    prefix = f"{directory}/"
    return any(
        entry.source_type is LayoutSourceType.AUDIO and path.startswith(prefix)
        for path, entry in index.files.items()
    )


def _descendant_directories(index: _LayoutIndex, directory: str) -> tuple[str, ...]:
    prefix = f"{directory}/"
    return tuple(
        path for path in _sort_paths(index.directories) if path.startswith(prefix)
    )


def _register_ancestors(
    canonical_path: str,
    physical_path: str,
    directories: set[str],
    children: dict[str, set[str]],
    directory_physical: dict[str, str],
) -> None:
    current_canonical = canonical_path
    current_physical = physical_path
    while current_canonical:
        directories.add(current_canonical)
        if current_canonical not in directory_physical:
            directory_physical[current_canonical] = current_physical
        parent_canonical = _parent_path(current_canonical)
        _add_child(children, parent_canonical, current_canonical)
        current_physical = _parent_path(current_physical)
        current_canonical = parent_canonical


def _add_child(children: dict[str, set[str]], parent: str, child: str) -> None:
    children.setdefault(parent, set()).add(child)


def _parent_path(path: str) -> str:
    if "/" not in path:
        return _ROOT
    return path.rsplit("/", 1)[0]


def _directory_paths(path: str) -> tuple[str, ...]:
    if not path:
        return ()
    parts = path.split("/")
    return tuple("/".join(parts[:index]) for index in range(1, len(parts) + 1))


def _directory_spellings(
    entries: Sequence[_NormalizedEntry],
) -> dict[str, set[str]]:
    spellings: dict[str, set[str]] = {}
    for entry in entries:
        if entry.entry_type is LayoutEntryType.DIRECTORY:
            canonical_dirs = _directory_paths(entry.canonical_path)
            physical_dirs = _directory_paths(entry.physical_path)
        else:
            canonical_dirs = _directory_paths(_parent_path(entry.canonical_path))
            physical_dirs = _directory_paths(_parent_path(entry.physical_path))
        for canonical_dir, physical_dir in zip(
            canonical_dirs, physical_dirs, strict=True
        ):
            spellings.setdefault(canonical_dir, set()).add(physical_dir)
    return spellings


def _is_under_directories(canonical_path: str, directories: set[str]) -> bool:
    current = canonical_path
    while current:
        if current in directories:
            return True
        current = _parent_path(current)
    return False


def _entry_name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _directory_name(index: _LayoutIndex, canonical_path: str) -> str:
    return _entry_name(index.directory_physical.get(canonical_path, canonical_path))


def _root_segment(path: str) -> str:
    return path.split("/", 1)[0]


def _file_stem(path: str) -> str:
    return PurePosixPath(_entry_name(path)).stem


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
