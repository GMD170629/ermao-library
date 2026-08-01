"""Pure import eligibility and preference policies."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from app.modules.imports.application.dto import ImportPreferencesDTO

REFLOWABLE_SOURCE_EXTS = {".mobi", ".azw", ".azw3", ".prc", ".fb2", ".txt"}


def extension_is_allowed(
    path: str | Path, preferences: ImportPreferencesDTO
) -> bool:
    candidate = Path(path)
    return (
        candidate.is_dir()
        or candidate.suffix.lower() in preferences.allowed_extensions
    )


def matches_ignore_patterns(path: str | Path, patterns: str | None) -> bool:
    candidate = Path(path)
    normalized_path = candidate.as_posix()
    requested = [
        line.strip() for line in (patterns or "").splitlines() if line.strip()
    ]
    return any(
        fnmatch.fnmatch(candidate.name, pattern)
        or fnmatch.fnmatch(normalized_path, pattern)
        or (
            "*" not in pattern
            and "?" not in pattern
            and pattern in candidate.name
        )
        for pattern in requested
    )
