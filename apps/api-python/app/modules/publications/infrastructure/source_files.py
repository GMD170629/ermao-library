"""Validated source-file resolution shared by publication format adapters."""

from __future__ import annotations

from pathlib import Path

from app.modules.publications.domain.model import PublicationCorruptError


def resolve_publication_source(raw_path: str, storage_root: Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = storage_root / candidate
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as error:
        raise PublicationCorruptError("publication source is unavailable") from error
    if not resolved.is_file():
        raise PublicationCorruptError("publication source is not a file")
    return resolved
