"""Monitor-folder path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.core.config import Settings


def normalize_monitor_root_path(value: Any) -> str:
    root_path = str(value or "").strip()
    if not root_path:
        return ""
    return os.path.normpath(root_path)


def is_inside_path(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def monitor_directory_tree_node(
    settings: Settings,
    requested_path: str | None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    monitor_root = settings.resolved_monitor_root
    if monitor_root is None:
        return None, "监控根目录未配置", 400

    try:
        real_monitor_root = monitor_root.resolve()
    except OSError:
        return None, "监控根目录不存在或不可读", 400

    if not real_monitor_root.exists() or not real_monitor_root.is_dir():
        return None, "监控根目录不存在或不可读", 400

    raw_path = str(requested_path or "").strip()
    if raw_path:
        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            return None, "请输入监控根目录下的绝对路径", 400
    else:
        target = real_monitor_root

    if not target.exists():
        return None, "路径不存在或不可读", 404

    try:
        real_target = target.resolve()
    except OSError:
        return None, "路径不存在或不可读", 404

    if not is_inside_path(real_monitor_root, real_target):
        return None, "路径真实位置不在监控根目录内", 403
    if not real_target.is_dir():
        return None, "监控文件夹路径必须是目录", 400

    children: list[dict[str, Any]] = []
    readable = os.access(real_target, os.R_OK)
    error: str | None = None
    if readable:
        try:
            for child in sorted(real_target.iterdir(), key=lambda item: item.name.lower()):
                try:
                    real_child = child.resolve()
                except OSError:
                    continue
                if not is_inside_path(real_monitor_root, real_child) or not real_child.is_dir():
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


def target_directory_from_path(settings: Settings, target_path: Any, action_label: str) -> Path:
    raw_path = str(target_path or "").strip()
    if not raw_path:
        raise ValueError(f"请选择{action_label}目录")
    monitor_root = settings.resolved_monitor_root
    if monitor_root is None:
        raise ValueError("监控根目录未配置")
    try:
        real_monitor_root = monitor_root.expanduser().resolve()
    except OSError:
        raise ValueError("监控根目录不存在或不可读")
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise ValueError(f"请选择监控根目录内的{action_label}目录")
    try:
        real_target = target.resolve()
    except OSError:
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not (real_monitor_root == real_target or is_inside_path(real_monitor_root, real_target)):
        raise ValueError(f"请选择监控根目录内的{action_label}目录")
    if not real_target.exists() or not real_target.is_dir():
        raise ValueError(f"所选{action_label}目录不存在或不可读")
    if not os.access(real_target, os.W_OK):
        raise ValueError(f"无法写入所选{action_label}目录，请检查 NAS 目录权限。")
    return real_target
