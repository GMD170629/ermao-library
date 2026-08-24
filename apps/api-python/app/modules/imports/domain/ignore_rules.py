"""Deterministic source-tree ignore rules for readable-resource imports."""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

IMPORT_IGNORE_PATTERNS_KEY = "import.ignorePatterns"

_COVER_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
_GLOB_MARKERS = frozenset("*?[")


def normalize_ignore_patterns(value: object) -> str:
    if not isinstance(value, str):
        return ""
    patterns = [
        line.strip() for line in value.replace("\r\n", "\n").split("\n") if line.strip()
    ]
    return "\n".join(patterns[:200])


def parse_ignore_patterns(value: str | None) -> tuple[str, ...]:
    return tuple(line.strip() for line in (value or "").splitlines() if line.strip())


def is_builtin_ignored_file(name: str) -> bool:
    """Return whether a regular file is metadata/cover input, not a resource."""

    normalized = name.casefold()
    if normalized.endswith(".opf"):
        return True
    for extension in _COVER_EXTENSIONS:
        if normalized == f"cover.{extension}" or normalized.endswith(
            f".cover.{extension}"
        ):
            return True
    return False


def matches_configured_ignore_patterns(
    relative_path: str | Path,
    patterns: str | None,
) -> bool:
    """Match one configured rule against basename and POSIX relative path.

    Literal rules retain the established basename-substring behavior used by
    manual uploads. Glob rules are deterministic across host platforms.
    """

    normalized_path = str(relative_path).replace("\\", "/").strip("/")
    name = PurePosixPath(normalized_path).name
    for pattern in parse_ignore_patterns(patterns):
        normalized_pattern = pattern.replace("\\", "/").strip()
        if not normalized_pattern:
            continue
        if fnmatch.fnmatchcase(name, normalized_pattern) or fnmatch.fnmatchcase(
            normalized_path, normalized_pattern
        ):
            return True
        if (
            not any(marker in normalized_pattern for marker in _GLOB_MARKERS)
            and normalized_pattern in name
        ):
            return True
    return False


def should_ignore_source_entry(
    *,
    relative_path: str,
    name: str,
    is_regular_file: bool,
    ignore_hidden: bool,
    library_patterns: str | None,
    global_patterns: str,
) -> bool:
    if ignore_hidden and name.startswith(".") and name not in {".", ".."}:
        return True
    if is_regular_file and is_builtin_ignored_file(name):
        return True
    return matches_configured_ignore_patterns(
        relative_path, global_patterns
    ) or matches_configured_ignore_patterns(relative_path, library_patterns)


__all__ = [
    "IMPORT_IGNORE_PATTERNS_KEY",
    "is_builtin_ignored_file",
    "matches_configured_ignore_patterns",
    "normalize_ignore_patterns",
    "parse_ignore_patterns",
    "should_ignore_source_entry",
]
