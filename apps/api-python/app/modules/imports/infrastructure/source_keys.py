"""Canonical, compact source keys used for scalable import deduplication."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


def canonical_source_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def source_key(path: str | Path) -> str:
    canonical = canonical_source_path(path)
    return sha256(str(canonical).encode("utf-8")).hexdigest()
