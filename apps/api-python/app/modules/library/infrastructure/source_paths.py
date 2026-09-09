"""Resolve existing library files using the detail adapter containment rules."""

from pathlib import Path


def resolve_existing_library_file(root_value: str, relative_value: str) -> Path | None:
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
        candidate = root.joinpath(*Path(relative_value).parts)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if resolved != candidate or not resolved.is_file():
        return None
    return resolved
