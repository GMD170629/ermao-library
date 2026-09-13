"""Library-root path helpers."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any


@dataclass(frozen=True)
class DirectoryMountSnapshot:
    resolve: Callable[[PurePath], str | None]
    browse_roots: tuple[Path, ...] | None

    def __call__(self, path: PurePath) -> str | None:
        return self.resolve(path)


class LibraryPathError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def is_inside_path(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def library_directory_tree_node(
    requested_path: str | None,
    *,
    mount_root_for_path: Callable[[Path], str | None],
    browse_roots: tuple[Path, ...] | None = None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    raw_path = str(requested_path or "").strip()
    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_absolute() and not (browse_roots is not None and raw_path == "/"):
            return None, "目录路径必须是绝对路径", 400
    else:
        target = Path("/")

    if browse_roots is not None and (
        not raw_path or target == Path("/")
        or any(target != root and target in root.parents for root in browse_roots)
    ):
        # A virtual root exposes nested mount points without exposing their
        # unmounted parent directories. It cannot itself be selected.
        return ({
            "name": "/", "path": "/", "readable": False,
            "mountRoot": None, "mountedOnly": True, "error": None,
            "children": [
                {"name": str(root), "path": str(root),
                 "readable": os.access(root, os.R_OK), "mountRoot": str(root)}
                for root in browse_roots if root.is_dir()
            ],
        }, None, 200)

    if not target.exists():
        return None, "路径不存在或不可读", 404

    try:
        real_target = target.resolve()
    except (OSError, RuntimeError):
        return None, "路径不存在或不可读", 404

    if not real_target.is_dir():
        return None, "书库路径必须是目录", 400

    if browse_roots is not None and mount_root_for_path(real_target) is None:
        return None, "路径不存在或不可读", 404

    children: list[dict[str, Any]] = []
    readable = os.access(real_target, os.R_OK)
    error: str | None = None
    if readable:
        try:
            for child in sorted(
                real_target.iterdir(), key=lambda item: item.name.lower()
            ):
                try:
                    real_child = child.resolve()
                except (OSError, RuntimeError):
                    continue
                if not real_child.is_dir():
                    continue
                if browse_roots is not None and mount_root_for_path(real_child) is None:
                    continue
                children.append(
                    {
                        "name": child.name,
                        "path": str(real_child),
                        "readable": os.access(real_child, os.R_OK),
                        "mountRoot": mount_root_for_path(real_child),
                    }
                )
        except OSError:
            readable = False
            error = "目录不可读取"
    else:
        error = "目录不可读取"

    return (
        {
            "name": real_target.name or str(real_target),
            "path": str(real_target),
            "readable": readable,
            "mountRoot": mount_root_for_path(real_target),
            "mountedOnly": browse_roots is not None,
            "error": error,
            "children": children[:200],
        },
        None,
        200,
    )


def target_directory_from_path(target_path: Any, action_label: str) -> Path:
    raw_path = str(target_path or "").strip()
    if not raw_path:
        raise ValueError(f"请选择{action_label}目录")
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise ValueError(f"请选择绝对{action_label}目录")
    try:
        real_target = target.resolve()
    except OSError:
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not real_target.exists() or not real_target.is_dir():
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not os.access(real_target, os.W_OK):
        raise ValueError(f"无法写入所选{action_label}目录，请检查 NAS 目录权限。")
    return real_target
