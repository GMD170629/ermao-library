"""Original reflowable publication formats supported without conversion."""

from __future__ import annotations

REFLOWABLE_SOURCE_EXTENSIONS = frozenset(
    {".mobi", ".azw", ".azw3", ".prc", ".fb2", ".txt"}
)

__all__ = ["REFLOWABLE_SOURCE_EXTENSIONS"]
