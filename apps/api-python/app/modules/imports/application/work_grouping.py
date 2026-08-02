"""Folder-first work grouping policy shared by non-audio imports."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportPreferencesDTO,
)
from app.modules.imports.application.identity_policy import (
    directory_merge_title_similarity,
    explicit_volume_range_start,
    normalize_directory_merge_title,
    parse_bracketed_series_identity,
)
from app.modules.imports.application.import_policy import (
    extension_is_allowed,
    matches_ignore_patterns,
)
from app.modules.imports.application.ports import ImportOrchestrationServices

WORK_GROUPING_SIMILARITY_THRESHOLD = 0.50


def resolve_non_audio_work_identity(
    services: ImportOrchestrationServices,
    options: ImportOptions,
    preferences: ImportPreferencesDTO,
) -> BookIdentityDTO:
    """Classify one publication as a parent-folder volume or standalone work."""

    source_path = (
        options.original_source_file_path or options.source_file_path
    ).resolve()
    filename = Path(options.original_name or source_path.name).name
    if options.requested_work_id:
        file_identity = services.recognize_filename_identity(filename)
        return replace(
            file_identity,
            reused_work_id=options.requested_work_id,
            grouping_kind="explicit",
            grouping_key=None,
            selection_reason="explicit_work",
        )

    file_signal = services.parse_filename_identity(filename)
    range_start = explicit_volume_range_start(Path(filename).stem)
    if file_signal.volume_index is None and range_start is not None:
        file_signal = replace(file_signal, volume_index=range_start)
    if services.is_monitor_root(source_path.parent):
        file_identity = services.recognize_filename_identity(filename)
        return replace(
            file_identity,
            volume_index=file_signal.volume_index,
            grouping_kind="monitor_root_file",
            grouping_key=f"monitor-root-file:{_path_fingerprint(source_path)}",
            selection_reason="direct_monitor_root_file",
        )

    parent_name = source_path.parent.name.strip()
    parent_signal = _parent_identity_signal(services, parent_name, filename)
    parent_is_similar = (
        directory_merge_title_similarity(file_signal.title, parent_signal.title)
        > WORK_GROUPING_SIMILARITY_THRESHOLD
    )
    parent_fingerprint = _path_fingerprint(source_path.parent)
    if file_signal.volume_index is not None or parent_is_similar:
        return _folder_identity(
            services,
            parent_name=parent_name,
            filename=filename,
            file_signal=file_signal,
            parent_fingerprint=parent_fingerprint,
        )

    sibling_snapshot = services.list_sibling_files(source_path)
    comparable_siblings = [
        sibling
        for sibling in sibling_snapshot.paths
        if extension_is_allowed(sibling, preferences)
        and not matches_ignore_patterns(sibling, preferences.ignore_patterns)
    ]
    has_similar_sibling = any(
        directory_merge_title_similarity(
            file_signal.title,
            services.parse_filename_identity(sibling.name).title,
        )
        > WORK_GROUPING_SIMILARITY_THRESHOLD
        for sibling in comparable_siblings
    )
    if sibling_snapshot.complete and not has_similar_sibling:
        file_identity = services.recognize_filename_identity(filename)
        return replace(
            file_identity,
            volume_index=file_signal.volume_index,
            grouping_kind="standalone",
            grouping_key=f"standalone:{parent_fingerprint}:{_title_fingerprint(file_signal.title)}",
            selection_reason="standalone_three_conditions_met",
        )
    return _folder_identity(
        services,
        parent_name=parent_name,
        filename=filename,
        file_signal=file_signal,
        parent_fingerprint=parent_fingerprint,
    )


def _parent_identity_signal(
    services: ImportOrchestrationServices,
    parent_name: str,
    filename: str,
) -> BookIdentityDTO:
    parent_identity = services.parse_filename_identity(f"{parent_name}.epub")
    bracketed_parent = parse_bracketed_series_identity(parent_name, filename)
    if bracketed_parent is None:
        return parent_identity
    return replace(
        parent_identity,
        title=bracketed_parent[0],
        author=bracketed_parent[1],
        volume_index=None,
        confidence=max(0.98, parent_identity.confidence),
    )


def _folder_identity(
    services: ImportOrchestrationServices,
    *,
    parent_name: str,
    filename: str,
    file_signal: BookIdentityDTO,
    parent_fingerprint: str,
) -> BookIdentityDTO:
    parent_identity = services.recognize_filename_identity(f"{parent_name}.epub")
    bracketed_parent = parse_bracketed_series_identity(parent_name, filename)
    if bracketed_parent is not None:
        parent_identity = replace(
            parent_identity,
            title=bracketed_parent[0],
            author=bracketed_parent[1],
            volume_index=None,
            confidence=max(0.98, parent_identity.confidence),
        )
    return replace(
        parent_identity,
        volume_index=file_signal.volume_index,
        grouping_kind="folder",
        grouping_key=f"folder:{parent_fingerprint}",
        selection_reason="folder_first_grouping",
        evidence=file_signal.evidence + parent_identity.evidence,
    )


def _path_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def _title_fingerprint(title: str) -> str:
    normalized = normalize_directory_merge_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
