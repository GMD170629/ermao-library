"""Filesystem path helpers for import presentation adapters."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.bootstrap.imports import (
    list_enabled_library_rows,
)
from app.modules.imports.application.library_paths import is_inside_path


def enabled_library_for_path(db: Session, target: Path) -> dict[str, object] | None:
    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in list_enabled_library_rows(db):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or is_inside_path(root, real_target):
            return folder
    return None


__all__ = ["enabled_library_for_path"]
