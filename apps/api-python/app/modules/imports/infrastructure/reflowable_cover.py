"""Atomic publication of covers embedded in native reflowable books."""

from __future__ import annotations

import os
from pathlib import Path

from app.modules.imports.application.reflowable_types import EmbeddedBookCover


def publish_reflowable_cover(
    storage_root: Path,
    work_id: str,
    version_id: str,
    volume_id: str,
    cover: EmbeddedBookCover | None,
) -> str | None:
    if cover is None:
        return None
    target = (
        storage_root
        / "books"
        / work_id
        / version_id
        / volume_id
        / f"cover{cover.extension}"
    )
    temporary = target.with_suffix(f"{target.suffix}.part")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(cover.content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)
