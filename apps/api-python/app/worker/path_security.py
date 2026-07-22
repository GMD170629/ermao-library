from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


class PathSecurityError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PathSecurityValidation:
    input_path: str
    real_path: Path
    monitor_root: Path
    real_monitor_root: Path


SENSITIVE_PATHS = [Path("/"), Path("/etc"), Path("/root"), Path("/proc"), Path("/sys"), Path("/dev"), Path("/var"), Path("/var/run"), Path("/run"), Path("/boot")]


def normalize_configured_path(value: str) -> str:
    trimmed = value.strip()
    if not trimmed or Path(trimmed).is_absolute():
        return trimmed
    root = os.environ.get("SHUKU_ROOT") or _find_workspace_root(Path.cwd()) or Path(os.environ.get("INIT_CWD", Path.cwd()))
    return str((Path(root) / trimmed).resolve())


def _find_workspace_root(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / "pnpm-workspace.yaml").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _is_inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _is_sensitive(path: Path) -> bool:
    candidates = [path.absolute(), path.resolve()]
    for candidate in candidates:
        for sensitive in SENSITIVE_PATHS:
            if candidate == sensitive:
                return True
            if sensitive != Path("/") and _is_inside(sensitive, candidate):
                return True
    return False


class PathSecurityService:
    def __init__(self, settings: Settings) -> None:
        monitor_root = settings.monitor_root or "/books"
        self.monitor_root = Path(normalize_configured_path(monitor_root))

    def validate_monitor_folder(self, input_path: str) -> PathSecurityValidation:
        validation = self._validate_path_inside_monitor_root(input_path)
        if not validation.real_path.is_dir():
            raise PathSecurityError(f"监控文件夹不是目录：{input_path}", "NOT_DIRECTORY")
        return validation

    def validate_file_access(self, input_path: str) -> PathSecurityValidation:
        validation = self._validate_path_inside_monitor_root(input_path)
        if not validation.real_path.is_file():
            raise PathSecurityError(f"文件不存在或不可读：{input_path}", "NOT_FILE")
        return validation

    def _validate_path_inside_monitor_root(self, input_path: str) -> PathSecurityValidation:
        trimmed = input_path.strip()
        if not trimmed:
            raise PathSecurityError("路径不能为空", "EMPTY_PATH")
        target = Path(trimmed)
        if not target.is_absolute():
            raise PathSecurityError(f"请输入监控根目录下的绝对路径：{trimmed}", "NOT_ABSOLUTE")
        if _is_sensitive(target):
            raise PathSecurityError(f"禁止访问系统敏感路径：{trimmed}", "SENSITIVE_PATH")
        if not self.monitor_root.is_absolute():
            raise PathSecurityError(f"监控根目录必须是绝对路径：{self.monitor_root}", "MONITOR_ROOT_UNAVAILABLE")
        if not self.monitor_root.exists():
            raise PathSecurityError(f"监控根目录不存在或不可读：{self.monitor_root}", "MONITOR_ROOT_UNAVAILABLE")
        real_monitor_root = self.monitor_root.resolve()
        if _is_sensitive(real_monitor_root):
            raise PathSecurityError(f"监控根目录不能指向系统敏感路径：{real_monitor_root}", "MONITOR_ROOT_UNAVAILABLE")
        if not target.exists():
            raise PathSecurityError(f"路径不存在或不可读：{trimmed}", "PATH_UNAVAILABLE")
        real_target = target.resolve()
        if _is_sensitive(real_target):
            raise PathSecurityError(f"禁止访问系统敏感路径：{real_target}", "SENSITIVE_PATH")
        if not _is_inside(real_monitor_root, real_target):
            raise PathSecurityError(f"路径真实位置不在监控根目录内：{trimmed} -> {real_target}", "OUTSIDE_MONITOR_ROOT")
        return PathSecurityValidation(trimmed, real_target, self.monitor_root, real_monitor_root)
