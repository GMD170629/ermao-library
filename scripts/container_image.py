"""Stopped image synchronization owned by the fixed launcher, never runtime code."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import IO, TypedDict

from container_install import (
    REQUIRED_RUNTIME_FILES,
    InstallError,
    backup_database,
    read_json,
    replace_runtime,
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

    def prepare(self) -> bool:
        if (self.record.exists() or self.record.is_symlink()) and image_identity(
            self.record
        ) == self.target:
            if not self.runtime.is_dir():
                raise InstallError("UNINITIALIZED_RUNTIME")
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
        database = self.storage / "database/shuku.sqlite3"
        if database.exists():
            backup_database(self.storage, self.state / "database-before-image.sqlite3")
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
        if not marker.exists():
            marker.write_text("1\n", encoding="utf-8")
        dependencies = self.storage / "dependencies"
        if dependencies.exists():
            shutil.rmtree(dependencies)
        initialize_dependencies(self.storage, self.dependency_seed)
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
        fixed = Path(__file__).with_name("environment.json")
        if (
            fixed.is_file()
            and self.target["environment"] != read_json(fixed)["environment"]
        ):
            raise InstallError("INCOMPATIBLE_IMAGE_ENVIRONMENT")
        if (self.seed / ".initialized").exists():
            raise InstallError("INVALID_IMAGE_SOURCE")
        if any(not (self.seed / name).is_file() for name in REQUIRED_RUNTIME_FILES):
            raise InstallError("INCOMPLETE_IMAGE")
        required = 64 * 1024 * 1024
        for source in (self.seed, self.dependency_seed):
            for path in source.rglob("*"):
                if path.is_symlink():
                    if os.path.isabs(os.readlink(path)) or not path.resolve(
                        strict=True
                    ).is_relative_to(source.resolve()):
                        raise InstallError("UNSAFE_IMAGE_SOURCE")
                elif path.is_file():
                    required += path.stat().st_size
                elif not path.is_dir():
                    raise InstallError("UNSAFE_IMAGE_SOURCE")
        manifest = validate_dependency_seed(self.dependency_seed)
        for package in manifest["packages"]:
            if package["ecosystem"] == "python":
                with zipfile.ZipFile(
                    self.dependency_seed / "wheels" / package["artifact"]["filename"]
                ) as wheel:
                    required += sum(item.file_size for item in wheel.infolist())
        for root in (
            self.runtime,
            self.storage / "dependencies",
            self.storage / "database",
        ):
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                raise InstallError("UNSAFE_STORAGE")
        database = self.storage / "database/shuku.sqlite3"
        if database.is_symlink():
            raise InstallError("UNSAFE_DATABASE")
        if database.exists():
            required += database.stat().st_size * 2
        if self.runtime.exists():
            marker = self.runtime / ".initialized"
            if not marker.is_file() or marker.is_symlink():
                raise InstallError("UNINITIALIZED_RUNTIME")
            image_identity(self.runtime / "application.json")
            if any(
                not (self.runtime / name).is_file() for name in REQUIRED_RUNTIME_FILES
            ):
                raise InstallError("INCOMPLETE_RUNTIME")
        elif (self.storage / "dependencies").exists():
            raise InstallError("ORPHANED_DEPENDENCIES")
        for root in (
            self.storage,
            self.state,
            self.runtime,
            self.storage / "dependencies",
        ):
            if not root.exists():
                continue
            for directory, _, _ in os.walk(root, followlinks=False):
                if not os.access(directory, os.W_OK | os.X_OK):
                    raise InstallError("STORAGE_NOT_WRITABLE")
                # Do not inspect unrelated user data below storage/update-tmp.
                if root in (self.storage, self.state):
                    break
        if shutil.disk_usage(self.storage).free < required:
            raise InstallError("INSUFFICIENT_SPACE")
        for name in ("preparation.json", "prepared"):
            path = self.state / name
            if path.is_symlink() or (
                path.exists()
                and not (path.is_dir() if name == "prepared" else path.is_file())
            ):
                raise InstallError("UNSAFE_STORAGE")

    def success(self) -> None:
        # Invalidate old preparation under the same lock before exposing new identity.
        (self.state / "preparation.json").unlink(missing_ok=True)
        prepared = self.state / "prepared"
        if prepared.exists():
            shutil.rmtree(prepared)
        write_json(self.record, self.target)
        (self.state / "installation-incomplete").unlink()
        self.close()
        print(
            f"image synchronization complete version={self.target['version']} / 镜像程序同步完成",
            flush=True,
        )

    def close(self) -> None:
        if self.lock is not None:
            self.lock.close()
            self.lock = None
