"""Map filesystem scan candidates to path-owned library topology sources."""

from __future__ import annotations

from pathlib import Path

from app.contracts.library_layout import (
    LayoutWork,
    LibraryOrganizationMode,
    parse_library_file_path,
)
from app.modules.imports.application.audio_types import is_supported_audio_file
from app.modules.imports.application.work_queue_dto import (
    PreparedScanSources,
    PreparedTopologySource,
    ScanErrorDTO,
)
from app.modules.imports.infrastructure.source_keys import source_key

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
        if canonical.is_dir() or (
            mode is LibraryOrganizationMode.AUDIOBOOK
        ) != is_supported_audio_file(canonical):
            rejected_count += 1
            errors.append(
                ScanErrorDTO(
                    path=str(canonical),
                    error="文件类型不属于当前书库的组织模式",
                    code="LIBRARY_LAYOUT_SOURCE_NOT_ALLOWED",
                )
            )
            continue
        try:
            relative_path = canonical.relative_to(root).as_posix()
        except ValueError:
            rejected_count += 1
            errors.append(
                ScanErrorDTO(
                    path=str(canonical),
                    error="文件路径不在书库根目录中",
                    code="LIBRARY_LAYOUT_INVALID_RELATIVE_PATH",
                )
            )
            continue
        result = parse_library_file_path(relative_path, mode)
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
        candidate_sources = (
            _sources_from_work(root, canonical, result.work)
            if result.work is not None
            else []
        )
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

    unique_sources = {item.source_key: item for item in prepared}
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


def _sources_from_work(
    root: Path,
    candidate: Path,
    work: LayoutWork,
) -> list[PreparedTopologySource]:
    sources: list[PreparedTopologySource] = []
    for version in work.versions:
        for volume_order, volume in enumerate(version.volumes):
            assets = tuple(
                root / asset.relative_path
                for asset in sorted(volume.assets, key=lambda item: item.order)
            )
            sources.append(
                PreparedTopologySource(
                    source_path=candidate,
                    source_key=source_key(candidate),
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


def _volume_format(assets: tuple[Path, ...]) -> str:
    if assets and is_supported_audio_file(assets[0]):
        return "AUDIO"
    if not assets:
        return "UNKNOWN"
    return assets[0].suffix.removeprefix(".").upper() or "UNKNOWN"
