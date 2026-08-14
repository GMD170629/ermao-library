"""Validated source-file resolution shared by publication format adapters."""

from __future__ import annotations

import hashlib
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


def publication_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise PublicationCorruptError("publication source cannot be read") from error
    return digest.hexdigest()
