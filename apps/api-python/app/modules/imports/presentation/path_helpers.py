"""Filesystem path helpers for import presentation adapters."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.bootstrap.imports import (
    list_enabled_library_rows,
)
from app.core.exception_diagnostics import record_exception
from app.modules.imports.application.library_paths import is_inside_path


def enabled_library_for_path(db: Session, target: Path) -> dict[str, object] | None:
    try:
        real_target = target.expanduser().resolve()
    except OSError as error:
        record_exception(
            logging.getLogger(__name__),
            "modules.imports.presentation.path_helpers.enabled_library_for_path.failed",
            error,
            context={"stage": "enabled_library_for_path"},
        )
        return None
    for folder in list_enabled_library_rows(db):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError as error:
            record_exception(
                logging.getLogger(__name__),
                "modules.imports.presentation.path_helpers.enabled_library_for_path.failed",
                error,
                context={"stage": "enabled_library_for_path"},
            )
            continue
        if root == real_target or is_inside_path(root, real_target):
            return folder
    return None


__all__ = ["enabled_library_for_path"]
