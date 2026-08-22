"""Validated source-file resolution shared by publication format adapters."""

from __future__ import annotations

from pathlib import Path

from app.modules.publications.domain.model import PublicationCorruptError


def select_publication_source_root(
    library_root: str | None,
    legacy_storage_root: Path,
) -> Path:
    """Prefer the owning Library root while retaining unavailable legacy fixtures."""

    if library_root:
        candidate = Path(library_root).expanduser()
        if candidate.is_dir():
            return candidate
    return legacy_storage_root


def resolve_publication_source(raw_path: str, source_root: Path) -> Path:
    try:
        resolved_root = source_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise PublicationCorruptError(
            "publication source root is unavailable"
        ) from error
    candidate = Path(raw_path)
    is_library_relative = not candidate.is_absolute()
    if is_library_relative:
        candidate = resolved_root / candidate
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as error:
        raise PublicationCorruptError("publication source is unavailable") from error
    if is_library_relative:
        try:
            resolved.relative_to(resolved_root)
        except ValueError as error:
            raise PublicationCorruptError(
                "publication source escapes its library"
            ) from error
    if not resolved.is_file():
        raise PublicationCorruptError("publication source is not a file")
    return resolved
