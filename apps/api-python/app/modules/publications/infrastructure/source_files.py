"""Validated source-file resolution shared by publication format adapters."""

from __future__ import annotations

from pathlib import Path

from app.modules.publications.domain.model import PublicationCorruptError


def select_publication_source_root(
    library_root: str | None,
    legacy_storage_root: Path,
) -> Path:
    """Select the owning Library root, without falling back across libraries."""

    if library_root:
        return Path(library_root).expanduser()
    return legacy_storage_root


def resolve_publication_source(raw_path: str, source_root: Path) -> Path:
    try:
        resolved_root = source_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise PublicationCorruptError(
            "publication source root is unavailable"
        ) from error
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as error:
        raise PublicationCorruptError("publication source is unavailable") from error
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise PublicationCorruptError(
            "publication source escapes its library"
        ) from error
    if not resolved.is_file():
        raise PublicationCorruptError("publication source is not a file")
    return resolved
