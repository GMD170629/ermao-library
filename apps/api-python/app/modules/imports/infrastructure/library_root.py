"""Resolve and validate a configured local library root."""

from __future__ import annotations

import os
from pathlib import Path

from app.modules.imports.application.library_paths import LibraryPathError


def resolve_library_root_path(value: object) -> Path:
    raw_path = str(value or "").strip()
    if not raw_path:
        raise LibraryPathError(
            "请选择书库路径",
            status_code=400,
            code="INVALID_LIBRARY_PATH",
        )
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise LibraryPathError(
            "书库路径必须是绝对路径",
            status_code=400,
            code="INVALID_LIBRARY_PATH",
        )
    try:
        real_target = target.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise LibraryPathError(
            "书库路径不存在或不可读",
            status_code=404,
            code="INVALID_LIBRARY_PATH",
        ) from error
    if not real_target.is_dir():
        raise LibraryPathError(
            "书库路径必须是目录",
            status_code=400,
            code="INVALID_LIBRARY_PATH",
        )
    if not os.access(real_target, os.R_OK):
        raise LibraryPathError(
            "书库路径不可读",
            status_code=400,
            code="INVALID_LIBRARY_PATH",
        )
    try:
        # os.access does not fully evaluate Windows ACLs. Probe the operation
        # needed by import without enumerating an entire large library.
        with os.scandir(real_target) as entries:
            next(entries, None)
    except OSError as error:
        raise LibraryPathError(
            "书库路径不可读",
            status_code=400,
            code="INVALID_LIBRARY_PATH",
        ) from error
    return real_target
