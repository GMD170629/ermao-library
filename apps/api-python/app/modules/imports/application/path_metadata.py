"""Filename metadata for sources already bound to directory topology."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    PathMetadataResolutionDTO,
)
from app.modules.imports.application.identity_policy import (
    UNKNOWN_AUTHOR,
    explicit_volume_range_start,
)
from app.modules.imports.application.ports import ImportOrchestrationServices


def resolve_non_audio_path_metadata(
    services: ImportOrchestrationServices,
    options: ImportOptions,
) -> PathMetadataResolutionDTO:
    """Read filename metadata without inspecting parent or sibling files."""

    source_path = (
        options.original_source_file_path or options.source_file_path
    ).resolve()
    filename = Path(options.original_name or source_path.name).name
    volume_title = Path(filename).stem.strip() or source_path.stem
    identity = _with_range_start(
        services.recognize_filename_identity(filename),
        volume_title,
    )
    work_title = identity.title.strip() or volume_title
    author = _usable_author(identity.author)
    normalized_identity = replace(
        identity,
        title=work_title,
        author=author or UNKNOWN_AUTHOR,
        selection_reason="filename_metadata",
    )
    return PathMetadataResolutionDTO(
        identity=normalized_identity,
        metadata=PublicationMetadata(
            title=work_title,
            volume_title=volume_title,
            authors=(author,) if author else (),
            volume_index=normalized_identity.volume_index,
        ),
    )


def _with_range_start(identity: BookIdentityDTO, volume_title: str) -> BookIdentityDTO:
    if identity.volume_index is not None:
        return identity
    range_start = explicit_volume_range_start(volume_title)
    return (
        replace(identity, volume_index=range_start)
        if range_start is not None
        else identity
    )


def _usable_author(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return None if not normalized or normalized == UNKNOWN_AUTHOR else normalized


__all__ = ["resolve_non_audio_path_metadata"]
