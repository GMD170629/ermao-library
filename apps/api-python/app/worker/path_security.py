from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class PathSecurityError(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PathSecurityValidation:
    input_path: str
    real_path: Path


class PathSecurityService:
    def validate_monitor_folder(self, input_path: str) -> PathSecurityValidation:
        validation = self._validate_absolute_path(input_path)
        if not validation.real_path.is_dir():
            raise PathSecurityError(
                f"监控文件夹不是目录：{input_path}", "NOT_DIRECTORY"
            )
        if not os.access(validation.real_path, os.R_OK):
            raise PathSecurityError(
                f"监控文件夹不可读：{input_path}", "PATH_UNAVAILABLE"
            )
        return validation

    def validate_file_access(self, input_path: str) -> PathSecurityValidation:
        validation = self._validate_absolute_path(input_path)
        if not validation.real_path.is_file():
            raise PathSecurityError(
                f"文件不存在或不可读：{input_path}", "NOT_FILE"
            )
        return validation

    def _validate_absolute_path(self, input_path: str) -> PathSecurityValidation:
        trimmed = input_path.strip()
        if not trimmed:
            raise PathSecurityError("路径不能为空", "EMPTY_PATH")
        target = Path(trimmed)
        if not target.is_absolute():
            raise PathSecurityError(
                f"监控文件夹路径必须是绝对路径：{trimmed}", "NOT_ABSOLUTE"
            )
        if not target.exists():
            raise PathSecurityError(
                f"路径不存在或不可读：{trimmed}", "PATH_UNAVAILABLE"
            )
        try:
            real_target = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathSecurityError(
                f"路径不存在或不可读：{trimmed}", "PATH_UNAVAILABLE"
            ) from exc
        return PathSecurityValidation(trimmed, real_target)
