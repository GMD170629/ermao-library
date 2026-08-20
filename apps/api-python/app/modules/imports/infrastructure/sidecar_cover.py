"""Atomic publication of a validated sidecar cover into managed storage."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def publish_sidecar_cover(
    storage_root: Path,
    source: Path,
    work_id: str,
    version_id: str,
    volume_id: str,
) -> str:
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    suffix = source.suffix.lower()
    if suffix not in allowed_suffixes:
        suffix = ".jpg"
    root = storage_root.resolve()
    target = root / "books" / work_id / version_id / volume_id / f"cover{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.part")
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target.relative_to(root))
