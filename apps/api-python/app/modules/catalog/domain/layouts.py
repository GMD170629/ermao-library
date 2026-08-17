"""Pure topology-v1 directory grammar interpreters for the catalog."""

import re
from collections import defaultdict
from collections.abc import Iterable

from app.modules.catalog.domain.model import (
    AdmissionKind,
    AssetCandidate,
    EntryType,
    LayoutResult,
    LayoutViolation,
    OrganizationMode,
    PathComparison,
    ProbedEntry,
    SourceKind,
    ViolationCode,
    VolumeCandidate,
)
from app.modules.catalog.domain.ordering import (
    comparison_path,
    natural_path_key,
)

_DISC_NAME = re.compile(r"(?i)^(disc|cd|disk)[ _.-]?([1-9][0-9]*)$")
_MAX_AUDIO_TRACKS = 10_000
_PRIMARY_ADMISSIONS = frozenset({AdmissionKind.PRIMARY, AdmissionKind.AUDIO_TRACK})
_EntryIndex = dict[tuple[str, ...], tuple[ProbedEntry, ...]]


def interpret_layout(
    mode: OrganizationMode,
    entries: Iterable[ProbedEntry],
    *,
    path_comparison: PathComparison,
) -> LayoutResult:
    """Interpret a bounded admission result without filesystem or database access."""

    if not isinstance(mode, OrganizationMode):
        raise TypeError("mode must be an OrganizationMode")
    if not isinstance(path_comparison, PathComparison):
        raise TypeError("path_comparison must be a PathComparison")

    received = tuple(entries)
    if any(not isinstance(entry, ProbedEntry) for entry in received):
        raise TypeError("entries must contain only ProbedEntry values")
    ordered = tuple(
        sorted(
            received,
            key=lambda entry: natural_path_key(entry.relative_path, path_comparison),
        )
    )
    entries_without_collisions, collision_violations = _remove_collisions(
        ordered, mode, path_comparison
    )
    entries_without_symlinks, symlink_violations = _preprocess_symlinks(
        entries_without_collisions, mode, path_comparison
    )
    children_index = _build_children_index(entries_without_symlinks, path_comparison)
    if mode is OrganizationMode.FLAT:
        result = _interpret_flat(
            entries_without_symlinks, children_index, path_comparison
        )
    elif mode is OrganizationMode.VOLUMES:
        result = _interpret_volumes(
            entries_without_symlinks, children_index, path_comparison
        )
    else:
        result = _interpret_audiobook(
            entries_without_symlinks, children_index, path_comparison
        )
    return LayoutResult(
        candidates=result.candidates,
        violations=_sort_violations(
            (*symlink_violations, *collision_violations, *result.violations),
            path_comparison,
        ),
    )


def _structural(entry: ProbedEntry) -> bool:
    if entry.entry_type is EntryType.SYMLINK:
        return False
    if entry.entry_type is EntryType.DIRECTORY:
        # Directories have no primary format. The admission probe may use
        # IGNORED as their neutral marker; their children still define the
        # grammar boundary.
        return True
    return entry.admission not in {
        AdmissionKind.SIDECAR,
        AdmissionKind.UNSUPPORTED,
        AdmissionKind.IGNORED,
    }


def _is_primary_file(entry: ProbedEntry) -> bool:
    return entry.entry_type is EntryType.FILE and entry.admission in _PRIMARY_ADMISSIONS


def _symlink_unit(mode: OrganizationMode, path: tuple[str, ...]) -> tuple[str, ...]:
    if mode is OrganizationMode.AUDIOBOOK and len(path) >= 2:
        return path[:1]
    if mode is OrganizationMode.VOLUMES and len(path) >= 3:
        return path[:3]
    return path


def _preprocess_symlinks(
    entries: tuple[ProbedEntry, ...],
    mode: OrganizationMode,
    comparison: PathComparison,
) -> tuple[tuple[ProbedEntry, ...], tuple[LayoutViolation, ...]]:
    symlinks = tuple(
        entry
        for entry in entries
        if entry.entry_type is EntryType.SYMLINK
        and not (mode is OrganizationMode.FLAT and len(entry.relative_path) != 1)
    )
    if not symlinks:
        return entries, ()

    blocked_units = tuple(
        comparison_path(_symlink_unit(mode, entry.relative_path), comparison)
        for entry in symlinks
    )
    remaining = tuple(
        entry
        for entry in entries
        if entry.entry_type is not EntryType.SYMLINK
        and not any(
            comparison_path(entry.relative_path, comparison)[: len(unit)] == unit
            for unit in blocked_units
        )
    )
    violations = tuple(
        LayoutViolation(
            code=ViolationCode.SYMLINK_NOT_ALLOWED,
            unit_path=_symlink_unit(mode, entry.relative_path),
            related_paths=(entry.relative_path,),
        )
        for entry in symlinks
    )
    return remaining, violations


def _build_children_index(
    entries: tuple[ProbedEntry, ...], comparison: PathComparison
) -> _EntryIndex:
    grouped: dict[tuple[str, ...], list[ProbedEntry]] = defaultdict(list)
    for entry in entries:
        grouped[comparison_path(entry.relative_path[:-1], comparison)].append(entry)
    return {parent: tuple(children) for parent, children in grouped.items()}


def _children(
    index: _EntryIndex, parent: tuple[str, ...], comparison: PathComparison
) -> tuple[ProbedEntry, ...]:
    return index.get(comparison_path(parent, comparison), ())


def _descendants(
    entries: tuple[ProbedEntry, ...],
    parent: tuple[str, ...],
    comparison: PathComparison,
) -> tuple[ProbedEntry, ...]:
    parent_key = comparison_path(parent, comparison)
    return tuple(
        entry
        for entry in entries
        if len(entry.relative_path) > len(parent)
        and comparison_path(entry.relative_path[: len(parent)], comparison)
        == parent_key
    )


def _asset(entry: ProbedEntry, *, order: int, disc_number: int = 0) -> AssetCandidate:
    if entry.source_format is None:
        raise ValueError("primary entry has no source_format")
    return AssetCandidate(
        path=entry.relative_path,
        source_format=entry.source_format,
        order=order,
        disc_number=disc_number,
    )


def _interpret_flat(
    entries: tuple[ProbedEntry, ...], index: _EntryIndex, comparison: PathComparison
) -> LayoutResult:
    candidates: list[VolumeCandidate] = []
    violations: list[LayoutViolation] = []
    for entry in _children(index, (), comparison):
        if entry.entry_type is EntryType.DIRECTORY and _structural(entry):
            violations.append(
                LayoutViolation(
                    code=ViolationCode.FLAT_NESTING_NOT_ALLOWED,
                    unit_path=entry.relative_path,
                    related_paths=(entry.relative_path,),
                )
            )
        elif _is_primary_file(entry):
            candidates.append(
                VolumeCandidate(
                    work_path=entry.relative_path,
                    version_path=None,
                    volume_path=entry.relative_path,
                    source_kind=SourceKind.SINGLE_FILE,
                    assets=(_asset(entry, order=0),),
                )
            )
    return LayoutResult(tuple(candidates), tuple(violations))


def _interpret_volumes(
    entries: tuple[ProbedEntry, ...], index: _EntryIndex, comparison: PathComparison
) -> LayoutResult:
    candidates: list[VolumeCandidate] = []
    violations: list[LayoutViolation] = []
    root_entries = _children(index, (), comparison)
    for entry in root_entries:
        if _is_primary_file(entry):
            violations.append(
                LayoutViolation(
                    code=ViolationCode.VERSION_DIRECTORY_REQUIRED,
                    unit_path=entry.relative_path,
                    related_paths=(entry.relative_path,),
                )
            )
    work_dirs = tuple(
        entry
        for entry in root_entries
        if entry.entry_type is EntryType.DIRECTORY and _structural(entry)
    )
    for work in work_dirs:
        work_children = _children(index, work.relative_path, comparison)
        for child in work_children:
            if _is_primary_file(child):
                violations.append(
                    LayoutViolation(
                        code=ViolationCode.VERSION_DIRECTORY_REQUIRED,
                        unit_path=child.relative_path,
                        related_paths=(child.relative_path,),
                    )
                )
        version_dirs = tuple(
            entry
            for entry in work_children
            if entry.entry_type is EntryType.DIRECTORY and _structural(entry)
        )
        for version in version_dirs:
            for child in _children(index, version.relative_path, comparison):
                if _is_primary_file(child):
                    candidates.append(
                        VolumeCandidate(
                            work_path=work.relative_path,
                            version_path=version.relative_path,
                            volume_path=child.relative_path,
                            source_kind=SourceKind.SINGLE_FILE,
                            assets=(_asset(child, order=0),),
                        )
                    )
                elif child.entry_type is EntryType.DIRECTORY and _structural(child):
                    assets, error = _collect_audio_volume(
                        entries,
                        index,
                        child.relative_path,
                        comparison,
                        non_audio_code=ViolationCode.BUNDLE_LAYOUT_AMBIGUOUS,
                        depth_code=ViolationCode.BUNDLE_LAYOUT_AMBIGUOUS,
                    )
                    if error is not None:
                        violations.append(
                            LayoutViolation(
                                code=error,
                                unit_path=child.relative_path,
                                related_paths=tuple(
                                    entry.relative_path
                                    for entry in _descendants(
                                        entries, child.relative_path, comparison
                                    )
                                    if _structural(entry)
                                ),
                            )
                        )
                    elif len(assets) > _MAX_AUDIO_TRACKS:
                        violations.append(
                            LayoutViolation(
                                code=ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED,
                                unit_path=child.relative_path,
                                related_paths=(child.relative_path,),
                            )
                        )
                    elif assets:
                        candidates.append(
                            VolumeCandidate(
                                work_path=work.relative_path,
                                version_path=version.relative_path,
                                volume_path=child.relative_path,
                                source_kind=SourceKind.MULTI_ASSET_AUDIO,
                                assets=assets,
                            )
                        )
    return LayoutResult(tuple(candidates), tuple(violations))


def _interpret_audiobook(
    entries: tuple[ProbedEntry, ...], index: _EntryIndex, comparison: PathComparison
) -> LayoutResult:
    candidates: list[VolumeCandidate] = []
    violations: list[LayoutViolation] = []
    for entry in _children(index, (), comparison):
        if _is_primary_file(entry):
            if entry.admission is AdmissionKind.AUDIO_TRACK:
                candidates.append(
                    VolumeCandidate(
                        work_path=entry.relative_path,
                        version_path=None,
                        volume_path=entry.relative_path,
                        source_kind=SourceKind.SINGLE_FILE,
                        assets=(_asset(entry, order=0),),
                    )
                )
            else:
                violations.append(
                    LayoutViolation(
                        code=ViolationCode.AUDIO_NON_AUDIO_RESOURCE,
                        unit_path=entry.relative_path,
                        related_paths=(entry.relative_path,),
                    )
                )
        elif entry.entry_type is EntryType.DIRECTORY and _structural(entry):
            work_candidates, work_violation = _interpret_audiobook_work(
                entries, index, entry.relative_path, comparison
            )
            if work_violation is not None:
                violations.append(work_violation)
            else:
                candidates.extend(work_candidates)
    return LayoutResult(tuple(candidates), tuple(violations))


def _interpret_audiobook_work(
    entries: tuple[ProbedEntry, ...],
    index: _EntryIndex,
    work_path: tuple[str, ...],
    comparison: PathComparison,
) -> tuple[tuple[VolumeCandidate, ...], LayoutViolation | None]:
    children = _children(index, work_path, comparison)
    direct_primary = tuple(entry for entry in children if _is_primary_file(entry))
    direct_audio = tuple(
        entry
        for entry in direct_primary
        if entry.admission is AdmissionKind.AUDIO_TRACK
    )
    direct_non_audio = tuple(
        entry for entry in direct_primary if entry.admission is AdmissionKind.PRIMARY
    )
    directories = tuple(
        entry
        for entry in children
        if entry.entry_type is EntryType.DIRECTORY and _structural(entry)
    )
    disc_dirs = tuple(
        entry
        for entry in directories
        if _disc_number(entry.relative_path[-1]) is not None
    )
    volume_dirs = tuple(
        entry for entry in directories if _disc_number(entry.relative_path[-1]) is None
    )

    if direct_non_audio:
        return (), LayoutViolation(
            code=ViolationCode.AUDIO_NON_AUDIO_RESOURCE,
            unit_path=work_path,
            related_paths=tuple(entry.relative_path for entry in direct_non_audio),
        )
    if (direct_audio or disc_dirs) and volume_dirs:
        return (), LayoutViolation(
            code=ViolationCode.AUDIO_LAYOUT_MIXED,
            unit_path=work_path,
            related_paths=tuple(
                entry.relative_path
                for entry in (*direct_audio, *disc_dirs, *volume_dirs)
            ),
        )

    candidates: list[VolumeCandidate] = []
    total_track_count = 0
    if direct_audio or disc_dirs:
        assets, error = _collect_audio_volume(
            entries,
            index,
            work_path,
            comparison,
            non_audio_code=ViolationCode.AUDIO_NON_AUDIO_RESOURCE,
            depth_code=ViolationCode.AUDIO_DEPTH_EXCEEDED,
        )
        if error is not None:
            return (), LayoutViolation(
                code=error,
                unit_path=work_path,
                related_paths=tuple(
                    entry.relative_path
                    for entry in _descendants(entries, work_path, comparison)
                    if _structural(entry)
                ),
            )
        if len(assets) > _MAX_AUDIO_TRACKS:
            return (), LayoutViolation(
                code=ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED,
                unit_path=work_path,
                related_paths=(work_path,),
            )
        if assets:
            candidates.append(
                VolumeCandidate(
                    work_path=work_path,
                    version_path=None,
                    volume_path=work_path,
                    source_kind=SourceKind.MULTI_ASSET_AUDIO,
                    assets=assets,
                )
            )
        return tuple(candidates), None

    for volume_dir in volume_dirs:
        assets, error = _collect_audio_volume(
            entries,
            index,
            volume_dir.relative_path,
            comparison,
            non_audio_code=ViolationCode.AUDIO_NON_AUDIO_RESOURCE,
            depth_code=ViolationCode.AUDIO_DEPTH_EXCEEDED,
        )
        if error is not None:
            return (), LayoutViolation(
                code=error,
                unit_path=work_path,
                related_paths=tuple(
                    entry.relative_path
                    for entry in _descendants(entries, work_path, comparison)
                    if _structural(entry)
                ),
            )
        total_track_count += len(assets)
        if total_track_count > _MAX_AUDIO_TRACKS:
            return (), LayoutViolation(
                code=ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED,
                unit_path=work_path,
                related_paths=(volume_dir.relative_path,),
            )
        if assets:
            candidates.append(
                VolumeCandidate(
                    work_path=work_path,
                    version_path=None,
                    volume_path=volume_dir.relative_path,
                    source_kind=SourceKind.MULTI_ASSET_AUDIO,
                    assets=assets,
                )
            )
    return tuple(candidates), None


def _collect_audio_volume(
    entries: tuple[ProbedEntry, ...],
    index: _EntryIndex,
    volume_path: tuple[str, ...],
    comparison: PathComparison,
    *,
    non_audio_code: ViolationCode,
    depth_code: ViolationCode,
) -> tuple[tuple[AssetCandidate, ...], ViolationCode | None]:
    direct = _children(index, volume_path, comparison)
    direct_audio = tuple(
        entry
        for entry in direct
        if _is_primary_file(entry) and entry.admission is AdmissionKind.AUDIO_TRACK
    )
    direct_non_audio = tuple(
        entry
        for entry in direct
        if _is_primary_file(entry) and entry.admission is AdmissionKind.PRIMARY
    )
    if direct_non_audio:
        return (), non_audio_code

    disc_dirs = tuple(
        entry
        for entry in direct
        if entry.entry_type is EntryType.DIRECTORY
        and _structural(entry)
        and _disc_number(entry.relative_path[-1]) is not None
    )
    other_dirs = tuple(
        entry
        for entry in direct
        if entry.entry_type is EntryType.DIRECTORY
        and _structural(entry)
        and _disc_number(entry.relative_path[-1]) is None
    )
    if other_dirs:
        return (), depth_code

    assets: list[AssetCandidate] = [
        _asset(entry, order=0, disc_number=0) for entry in direct_audio
    ]
    for disc_dir in disc_dirs:
        disc_number = _disc_number(disc_dir.relative_path[-1])
        if disc_number is None:
            return (), depth_code
        disc_children = _children(index, disc_dir.relative_path, comparison)
        disc_audio = tuple(
            entry
            for entry in disc_children
            if _is_primary_file(entry) and entry.admission is AdmissionKind.AUDIO_TRACK
        )
        disc_non_audio = tuple(
            entry
            for entry in disc_children
            if _is_primary_file(entry) and entry.admission is AdmissionKind.PRIMARY
        )
        nested_dirs = tuple(
            entry
            for entry in disc_children
            if entry.entry_type is EntryType.DIRECTORY and _structural(entry)
        )
        if disc_non_audio:
            return (), non_audio_code
        if nested_dirs:
            return (), depth_code
        assets.extend(
            _asset(entry, order=0, disc_number=disc_number) for entry in disc_audio
        )

    assets.sort(
        key=lambda asset: (
            asset.disc_number,
            natural_path_key(asset.path, comparison),
        )
    )
    ordered = tuple(
        AssetCandidate(
            path=asset.path,
            source_format=asset.source_format,
            order=index,
            disc_number=asset.disc_number,
        )
        for index, asset in enumerate(assets)
    )
    return ordered, None


def _disc_number(name: str) -> int | None:
    match = _DISC_NAME.fullmatch(name)
    return int(match.group(2)) if match else None


def _collision_unit(mode: OrganizationMode, path: tuple[str, ...]) -> tuple[str, ...]:
    if mode is OrganizationMode.FLAT:
        return path[:1]
    if mode is OrganizationMode.AUDIOBOOK:
        return path[:1]
    if len(path) == 1:
        return path[:1]
    if len(path) == 2:
        return path
    return path[:3]


def _remove_collisions(
    entries: tuple[ProbedEntry, ...],
    mode: OrganizationMode,
    comparison: PathComparison,
) -> tuple[tuple[ProbedEntry, ...], tuple[LayoutViolation, ...]]:
    collision_entries = (
        tuple(entry for entry in entries if len(entry.relative_path) == 1)
        if mode is OrganizationMode.FLAT
        else entries
    )
    grouped: dict[tuple[str, ...], list[ProbedEntry]] = defaultdict(list)
    for entry in collision_entries:
        grouped[comparison_path(entry.relative_path, comparison)].append(entry)
    collision_keys = tuple(key for key, group in grouped.items() if len(group) > 1)
    minimal_keys = tuple(
        sorted(
            (
                key
                for key in collision_keys
                if not any(
                    len(parent) < len(key) and key[: len(parent)] == parent
                    for parent in collision_keys
                )
            ),
            key=lambda key: (len(key), key),
        )
    )
    if not minimal_keys:
        return entries, ()
    violations: list[LayoutViolation] = []
    for key in minimal_keys:
        group = grouped[key]
        related = tuple(
            entry.relative_path
            for entry in sorted(
                group,
                key=lambda entry: natural_path_key(entry.relative_path, comparison),
            )
        )
        violations.append(
            LayoutViolation(
                code=ViolationCode.PATH_NORMALIZATION_COLLISION,
                unit_path=_collision_unit(mode, related[0]),
                related_paths=related,
            )
        )

    blocked_units = tuple(
        comparison_path(_collision_unit(mode, key), comparison) for key in minimal_keys
    )

    def blocked(entry: ProbedEntry) -> bool:
        path = comparison_path(entry.relative_path, comparison)
        return any(path[: len(unit)] == unit for unit in blocked_units)

    return tuple(entry for entry in entries if not blocked(entry)), tuple(violations)


def _sort_violations(
    violations: tuple[LayoutViolation, ...], comparison: PathComparison
) -> tuple[LayoutViolation, ...]:
    return tuple(
        sorted(
            violations,
            key=lambda violation: (
                natural_path_key(violation.unit_path, comparison),
                violation.code.value,
                tuple(
                    natural_path_key(path, comparison)
                    for path in violation.related_paths
                ),
            ),
        )
    )
