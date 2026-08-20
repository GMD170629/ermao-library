"""Map filesystem scan candidates to path-owned library topology sources."""

from __future__ import annotations

from pathlib import Path

from app.contracts.library_layout import (
    LayoutEntry,
    LayoutEntryType,
    LayoutSourceType,
    LayoutWork,
    LibraryOrganizationMode,
    interpret_library_layout,
)
from app.modules.imports.application.audio_types import is_supported_audio_file
from app.modules.imports.application.work_queue_dto import (
    PreparedScanSources,
    PreparedTopologySource,
    ScanErrorDTO,
)
from app.modules.imports.infrastructure.source_keys import source_key
from app.services.audio_metadata import collect_audio_bundle_files

_VOLUME_KEY_PREFIX = "volume:"


def prepare_topology_sources(
    candidates: tuple[Path, ...],
    *,
    library_root: Path,
    organization_mode: str,
) -> PreparedScanSources:
    """Resolve candidates and interpret only their path-derived structure."""

    if len(candidates) > 500:
        raise ValueError("scan candidate batches cannot exceed 500 sources")
    root = library_root.expanduser().resolve()
    mode = LibraryOrganizationMode(organization_mode)
    prepared: list[PreparedTopologySource] = []
    errors: list[ScanErrorDTO] = []
    rejected_count = 0
    for candidate in candidates:
        canonical = candidate.expanduser().resolve()
        entries = _layout_entries(canonical, root)
        result = interpret_library_layout(entries, mode)
        if result.violations:
            rejected_count += 1
            errors.extend(
                ScanErrorDTO(
                    path=str(root / violation.relative_path),
                    error="目录结构不符合书库的组织模式",
                    code=f"LIBRARY_LAYOUT_{violation.code.value}",
                )
                for violation in result.violations
            )
            continue
        candidate_sources = _sources_from_layout(root, result.works)
        if not candidate_sources:
            rejected_count += 1
            errors.append(
                ScanErrorDTO(
                    path=str(canonical),
                    error="文件类型不属于当前书库的组织模式",
                    code="LIBRARY_LAYOUT_SOURCE_NOT_ALLOWED",
                )
            )
            continue
        prepared.extend(candidate_sources)

    unique_sources = {
        item.source_key: item
        for item in prepared
    }
    topology_sources = tuple(unique_sources.values())
    return PreparedScanSources(
        topology_sources=topology_sources,
        source_pairs=tuple(
            (item.source_key, str(item.source_path)) for item in topology_sources
        ),
        candidate_count=len(candidates),
        rejected_count=rejected_count,
        errors=tuple(errors),
    )


def _layout_entries(candidate: Path, root: Path) -> tuple[LayoutEntry, ...]:
    if candidate.is_dir():
        paths = tuple(collect_audio_bundle_files(candidate))
    else:
        paths = (candidate,)
    entries: list[LayoutEntry] = []
    for path in paths:
        relative_path = path.resolve().relative_to(root).as_posix()
        source_type = (
            LayoutSourceType.AUDIO
            if is_supported_audio_file(path)
            else LayoutSourceType.PUBLICATION
        )
        entries.append(
            LayoutEntry(
                relative_path=relative_path,
                entry_type=LayoutEntryType.FILE,
                source_type=source_type,
            )
        )
    return tuple(entries)


def _sources_from_layout(
    root: Path,
    works: tuple[LayoutWork, ...],
) -> list[PreparedTopologySource]:
    sources: list[PreparedTopologySource] = []
    for work in works:
        for version in work.versions:
            for volume_order, volume in enumerate(version.volumes):
                assets = tuple(
                    root / asset.relative_path
                    for asset in sorted(volume.assets, key=lambda item: item.order)
                )
                source_path = _volume_source_path(root, volume.source_key)
                sources.append(
                    PreparedTopologySource(
                        source_path=source_path,
                        source_key=source_key(source_path),
                        work_source_key=work.source_key,
                        work_title=work.source_name,
                        version_source_key=version.source_key,
                        version_name=version.source_name,
                        volume_resource_key=volume.source_key,
                        volume_title=volume.source_name,
                        volume_sort_order=volume_order,
                        volume_format=_volume_format(assets),
                        asset_paths=assets,
                    )
                )
    return sources


def _volume_source_path(
    root: Path,
    volume_source_key: str,
) -> Path:
    relative_path = volume_source_key.removeprefix(_VOLUME_KEY_PREFIX)
    return root / relative_path


def _volume_format(assets: tuple[Path, ...]) -> str:
    if assets and is_supported_audio_file(assets[0]):
        return "AUDIO"
    if not assets:
        return "UNKNOWN"
    return assets[0].suffix.removeprefix(".").upper() or "UNKNOWN"
