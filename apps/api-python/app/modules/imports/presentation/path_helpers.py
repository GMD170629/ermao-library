"""Library-root path helpers for download and import HTTP adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.bootstrap.imports import import_http_store
from app.bootstrap.system import upsert_setting
from app.modules.imports.application.library_paths import is_inside_path


def has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def enabled_library_for_path(db: Session, target: Path) -> dict[str, Any] | None:
    if not has_table(db, "Library"):
        return None
    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in import_http_store.list_enabled_library_rows(db):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or is_inside_path(root, real_target):
            return folder
    return None


def save_system_setting(db: Session, key: str, value: Any) -> None:
    upsert_setting(db, key, value)
