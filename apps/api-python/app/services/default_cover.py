"""Identity of the bundled book fallback cover served when a Book has none."""

from __future__ import annotations

from pathlib import Path

DEFAULT_COVER_ASSET_PATH = (
    Path(__file__).resolve().parent.parent / "assets/default-book-cover-v2.webp"
)
# Legacy versions persisted this file name into metadata; keep recognizing it so
# stale rows never resolve to a real cover or get re-published.
_DEFAULT_COVER_FILE_NAMES = frozenset(
    {
        "default-book-cover-v1.png",
        "default-book-cover-v2.webp",
    }
)


def is_default_cover_path(value: object) -> bool:
    if not value:
        return False
    return Path(str(value)).name in _DEFAULT_COVER_FILE_NAMES


__all__ = ["DEFAULT_COVER_ASSET_PATH", "is_default_cover_path"]
