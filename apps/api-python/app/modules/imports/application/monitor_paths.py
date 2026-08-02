"""Monitor-folder path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class MonitorPathError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def resolve_monitor_folder_path(value: object) -> Path:
    raw_path = str(value or "").strip()
    if not raw_path:
        raise MonitorPathError(
            "请选择监控文件夹路径",
            status_code=400,
            code="MONITOR_FOLDER_PATH_REQUIRED",
        )
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise MonitorPathError(
            "监控文件夹路径必须是绝对路径",
            status_code=400,
            code="MONITOR_FOLDER_PATH_NOT_ABSOLUTE",
        )
    try:
        real_target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise MonitorPathError(
            "监控文件夹路径不存在或不可读",
            status_code=404,
            code="MONITOR_FOLDER_PATH_UNAVAILABLE",
        ) from None
    if not real_target.is_dir():
        raise MonitorPathError(
            "监控文件夹路径必须是目录",
            status_code=400,
            code="MONITOR_FOLDER_PATH_NOT_DIRECTORY",
        )
    if not os.access(real_target, os.R_OK):
        raise MonitorPathError(
            "监控文件夹路径不可读",
            status_code=400,
            code="MONITOR_FOLDER_PATH_UNREADABLE",
        )
    return real_target


def is_inside_path(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def monitor_directory_tree_node(
    requested_path: str | None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    raw_path = str(requested_path or "").strip()
    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            return None, "目录路径必须是绝对路径", 400
    else:
        target = Path("/")

    if not target.exists():
        return None, "路径不存在或不可读", 404

    try:
        real_target = target.resolve()
    except (OSError, RuntimeError):
        return None, "路径不存在或不可读", 404

    if not real_target.is_dir():
        return None, "监控文件夹路径必须是目录", 400

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
                children.append(
                    {
                        "name": child.name,
                        "path": str(real_child),
                        "readable": os.access(real_child, os.R_OK),
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
            "error": error,
            "children": children[:200],
        },
        None,
        200,
    )


def target_directory_from_path(
    target_path: Any, action_label: str
) -> Path:
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
