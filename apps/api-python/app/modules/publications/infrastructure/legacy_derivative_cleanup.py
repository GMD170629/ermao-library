"""Remove storage owned exclusively by the retired Reader derivative pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path


def remove_retired_reader_derivatives(storage_root: Path) -> bool:
    """Delete only the former Reader derivative directory, failing on path escape."""

    root = storage_root.resolve()
    target = root / "cache" / "publication-render"
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            "retired Reader derivative path escapes storage root"
        ) from error

    if target.is_symlink():
        target.unlink()
        return True
    if not target.exists():
        return False
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            "retired Reader derivative path escapes storage root"
        ) from error
    shutil.rmtree(target)
    return True


__all__ = ["remove_retired_reader_derivatives"]
