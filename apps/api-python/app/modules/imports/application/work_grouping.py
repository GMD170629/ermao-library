"""Unified non-audio PATH metadata orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Literal

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportPreferencesDTO,
    NonAudioPathResolutionDTO,
)
from app.modules.imports.application.identity_policy import (
    UNKNOWN_AUTHOR,
    explicit_volume_range_start,
    normalize_directory_merge_title,
    parse_bracketed_series_identity,
)
from app.modules.imports.application.ports import ImportOrchestrationServices
from app.modules.imports.domain.path_metadata import (
    path_media_family,
    path_titles_are_related,
)


def resolve_non_audio_work_identity(
    services: ImportOrchestrationServices,
    options: ImportOptions,
    preferences: ImportPreferencesDTO,
) -> NonAudioPathResolutionDTO:
    """Resolve one immutable PATH candidate before other metadata sources merge."""

    source_path = (
        options.original_source_file_path or options.source_file_path
    ).resolve()
    filename = Path(options.original_name or source_path.name).name
    volume_title = Path(filename).stem.strip()
    file_signal = _with_range_start(
        services.parse_filename_identity(filename),
        volume_title,
    )
    monitor_root = services.monitor_root_path(options.monitor_folder_id)
    is_monitor_root_file = _is_direct_monitor_root_file(
        source_path,
        monitor_root,
    )

    use_parent = False
    parent_signal: BookIdentityDTO | None = None
    parent_filename: str | None = None
    if not is_monitor_root_file:
        parent_filename = f"{source_path.parent.name.strip()}{source_path.suffix}"
        parent_signal = _parent_identity_signal(
            services,
            parent_name=source_path.parent.name.strip(),
            parent_filename=parent_filename,
            child_filename=filename,
        )
        use_parent = file_signal.volume_index is not None
        if not use_parent:
            use_parent = path_titles_are_related(parent_signal.title, file_signal.title)
        if not use_parent:
            use_parent = _has_related_sibling(
                services,
                source_path=source_path,
                filename=filename,
                file_title=file_signal.title,
                preferences=preferences,
                media_kind_policy=options.media_kind_policy,
            )

    selected_filename = parent_filename if use_parent else filename
    selected_signal = parent_signal if use_parent else file_signal
    if selected_filename is None or selected_signal is None:
        raise RuntimeError("path metadata selection produced no filename identity")
    advanced_identity = services.recognize_filename_identity(selected_filename)
    work_title = (
        advanced_identity.title.strip()
        if advanced_identity.source == "ai" and advanced_identity.title.strip()
        else selected_signal.title.strip()
    )
    author = _usable_author(advanced_identity.author) or _usable_author(
        selected_signal.author
    )
    volume_index = file_signal.volume_index
    parent_fingerprint = _path_fingerprint(source_path.parent)

    grouping_kind: Literal["folder", "standalone", "monitor_root_file"]
    if use_parent:
        grouping_kind = "folder"
        grouping_key = f"folder:{parent_fingerprint}"
        selection_reason = "parent_path_metadata"
        series_name = work_title
    elif is_monitor_root_file:
        grouping_kind = "monitor_root_file"
        grouping_key = f"monitor-root-file:{_path_fingerprint(source_path)}"
        selection_reason = "direct_monitor_root_file"
        series_name = None
    else:
        grouping_kind = "standalone"
        grouping_key = (
            f"standalone:{parent_fingerprint}:{_title_fingerprint(file_signal.title)}"
        )
        selection_reason = "insufficient_parent_path_evidence"
        series_name = None

    identity = replace(
        advanced_identity,
        title=work_title,
        author=author or UNKNOWN_AUTHOR,
        volume_index=volume_index,
        grouping_kind=grouping_kind,
        grouping_key=grouping_key,
        selection_reason=selection_reason,
        evidence=file_signal.evidence + advanced_identity.evidence,
    )
    metadata = PublicationMetadata(
        title=work_title,
        volume_title=volume_title,
        authors=(author,) if author else (),
        series_name=series_name,
        volume_index=volume_index,
    )
    return NonAudioPathResolutionDTO(identity=identity, metadata=metadata)


def _with_range_start(identity: BookIdentityDTO, volume_title: str) -> BookIdentityDTO:
    if identity.volume_index is not None:
        return identity
    range_start = explicit_volume_range_start(volume_title)
    return (
        replace(identity, volume_index=range_start)
        if range_start is not None
        else identity
    )


def _parent_identity_signal(
    services: ImportOrchestrationServices,
    *,
    parent_name: str,
    parent_filename: str,
    child_filename: str,
) -> BookIdentityDTO:
    identity = services.parse_filename_identity(parent_filename)
    bracketed = parse_bracketed_series_identity(parent_name, child_filename)
    if bracketed is None:
        return identity
    return replace(
        identity,
        title=bracketed[0],
        author=bracketed[1],
        volume_index=None,
        confidence=max(identity.confidence, 0.98),
    )


def _is_direct_monitor_root_file(
    source_path: Path,
    monitor_root: Path | None,
) -> bool:
    if monitor_root is None:
        return True
    resolved_root = monitor_root.resolve()
    try:
        source_path.relative_to(resolved_root)
    except ValueError:
        return True
    return source_path.parent == resolved_root


def _has_related_sibling(
    services: ImportOrchestrationServices,
    *,
    source_path: Path,
    filename: str,
    file_title: str,
    preferences: ImportPreferencesDTO,
    media_kind_policy: str,
) -> bool:
    current_family = path_media_family(
        filename,
        media_kind_policy=media_kind_policy,
        allowed_extensions=preferences.allowed_extensions,
    )
    if current_family is None:
        return False
    siblings = services.list_sibling_files(source_path)
    for sibling in siblings.paths:
        sibling_family = path_media_family(
            sibling.name,
            media_kind_policy=media_kind_policy,
            allowed_extensions=preferences.allowed_extensions,
        )
        if sibling_family != current_family:
            continue
        sibling_signal = services.parse_filename_identity(sibling.name)
        if path_titles_are_related(sibling_signal.title, file_title):
            return True
    return False


def _usable_author(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return None if not normalized or normalized == UNKNOWN_AUTHOR else normalized


def _path_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def _title_fingerprint(title: str) -> str:
    normalized = normalize_directory_merge_title(title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
