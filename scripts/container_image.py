"""Stopped image synchronization owned by the fixed launcher, never runtime code."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
from pathlib import Path
from typing import IO, TypedDict

from container_install import (
    REQUIRED_RUNTIME_FILES,
    InstallError,
    read_json,
    replace_runtime,
    update_warning,
    write_json,
)
from dependency_environment import initialize_dependencies, validate_dependency_seed


class ImageIdentity(TypedDict):
    version: str
    protocol: int
    environment: dict[str, str | int]


def image_identity(path: Path) -> ImageIdentity:
    value = read_json(path)
    if not isinstance(value, dict):
        raise InstallError("INVALID_IMAGE_IDENTITY")
    environment = value.get("environment")
    version = value.get("version")
    protocol = value.get("protocol", 1)
    if (
        not isinstance(version, str)
        or not re.fullmatch(
            r"(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})", version
        )
        or type(protocol) is not int
        or protocol not in (1, 2)
        or not isinstance(environment, dict)
        or environment.get("format") != 1
        or not all(
            isinstance(environment.get(k), str) and environment[k]
            for k in ("platform", "compatibility")
        )
    ):
        raise InstallError("INVALID_IMAGE_IDENTITY")
    return {"version": version, "protocol": protocol, "environment": environment}


class ImageSynchronization:
    def __init__(self, storage: Path, seed: Path, dependency_seed: Path) -> None:
        self.storage = storage
        self.seed = seed
        self.dependency_seed = dependency_seed
        self.runtime = storage / "runtime"
        self.state = storage / "update-tmp"
        self.record = self.state / "image.json"
        self.target = image_identity(seed / "application.json")
        self.lock: IO[str] | None = None
        self.dependencies_recorded = False

    def prepare(self) -> bool:
        try:
            same_image = image_identity(self.record) == self.target
        except (OSError, ValueError, TypeError, KeyError, InstallError):
            same_image = False
            update_warning("IMAGE_RECORD_UNAVAILABLE")
        incomplete = self.state / "installation-incomplete"
        if (
            same_image
            and self.runtime.is_dir()
            and not (incomplete.exists() or incomplete.is_symlink())
        ):
            return False
        self.lock = os.fdopen(
            os.open(
                self.state / "prepare.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            ),
            "w",
        )
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.preflight()
        write_json(
            self.state / "installation-incomplete",
            {"source": "image", "target": self.target},
        )
        print(
            f"image synchronization version={self.target['version']} / 正在同步镜像程序及依赖",
            flush=True,
        )
        replace_runtime(self.seed, self.runtime)
        marker = self.runtime / ".initialized"
        try:
            if not marker.exists() and not marker.is_symlink():
                marker.write_text("1\n", encoding="utf-8")
        except OSError:
            update_warning("INITIALIZATION_RECORD_WRITE_FAILED")
        dependencies = self.storage / "dependencies"
        if dependencies.exists():
            shutil.rmtree(dependencies)
        self.dependencies_recorded = initialize_dependencies(
            self.storage, self.dependency_seed
        )
        return True

    def preflight(self) -> None:
        if self.target["protocol"] != 2:
            raise InstallError("UNSUPPORTED_IMAGE_PROTOCOL")
        for source in (self.seed, self.dependency_seed):
            if (
                source.is_symlink()
                or not source.is_dir()
                or source.resolve().is_relative_to(self.storage)
            ):
                raise InstallError("UNSAFE_IMAGE_SOURCE")
        if any(not (self.seed / name).is_file() for name in REQUIRED_RUNTIME_FILES):
            raise InstallError("INCOMPLETE_IMAGE")
        for source in (self.seed, self.dependency_seed):
            for path in source.rglob("*"):
                if path.is_symlink():
                    if os.path.isabs(os.readlink(path)) or not path.resolve(
                        strict=True
                    ).is_relative_to(source.resolve()):
                        raise InstallError("UNSAFE_IMAGE_SOURCE")
                elif not path.is_file() and not path.is_dir():
                    raise InstallError("UNSAFE_IMAGE_SOURCE")
        validate_dependency_seed(self.dependency_seed)
        for root in (
            self.runtime,
            self.storage / "dependencies",
        ):
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                raise InstallError("UNSAFE_STORAGE")

    def success(self) -> None:
        for name in ("preparation.json", "prepared"):
            try:
                path = self.state / name
                if path.is_symlink() or not path.is_dir():
                    path.unlink(missing_ok=True)
                else:
                    shutil.rmtree(path)
            except OSError:
                update_warning("IMAGE_CLEANUP_FAILED")
        try:
            write_json(self.record, self.target)
        except OSError:
            update_warning("IMAGE_RECORD_WRITE_FAILED")
        if self.dependencies_recorded:
            try:
                (self.state / "installation-incomplete").unlink(missing_ok=True)
            except OSError:
                update_warning("IMAGE_CLEANUP_FAILED")
        self.close()
        print(
            f"image synchronization complete version={self.target['version']} / 镜像程序同步完成",
            flush=True,
        )

    def close(self) -> None:
        if self.lock is not None:
            self.lock.close()
            self.lock = None
