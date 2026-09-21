"""Fixed protocol 2 executor. Standard library only; never imports runtime code."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

from dependency_packages import digest
from shuku_dependencies.installed import (
    bounded_json,
)
from shuku_dependencies.packages import dependency_difference
from shuku_dependencies.packages import dependency_key as key


class DependencyInstallError(RuntimeError):
    pass


def update_warning(code: str) -> None:
    print(f"update warning / 更新提醒：{code}", file=sys.stderr, flush=True)


def safe_destination(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if (
        not relative
        or any(p in ("", ".", "..") for p in parts)
        or "\\" in relative
        or ":" in relative
    ):
        raise DependencyInstallError("UNSAFE_STORAGE")
    path = root
    for part in parts[:-1]:
        path /= part
        if path.is_symlink():
            raise DependencyInstallError("UNSAFE_STORAGE")
    return root / relative


class DependencyInstallation:
    def __init__(
        self,
        storage: Path,
        request: dict,
        state: dict,
        fixed: Path,
        *,
        uv: str = "/usr/local/bin/uv",
        cancelled: Callable[[], bool] = lambda: False,
    ):
        self.storage, self.request, self.state = storage, request, state
        self.work = storage / "update-tmp/prepared"
        self.runtime = storage / "runtime"
        self.python = storage / "dependencies/python/bin/python"
        self.uv, self.cancelled = uv, cancelled
        self.fixed = fixed
        self.result: dict | None = None
        self.load()

    def load(self) -> None:
        for relative in (
            "update-tmp",
            "update-tmp/prepared",
            "dependencies",
            "dependencies/python",
            "runtime",
        ):
            path = safe_destination(self.storage, relative)
            if path.is_symlink():
                raise DependencyInstallError("UNSAFE_STORAGE")
        target = self.request["target"]
        manifest_path = self.work / "release.json"
        self.manifest = bounded_json(manifest_path, 32 * 1024 * 1024)
        if digest(manifest_path) != target["sha256"]:
            raise DependencyInstallError("DIGEST_MISMATCH")
        self.local = bounded_json(self.storage / "dependencies/installed.json")
        self.target = self.manifest["dependencies"]
        self.old = {key(p): p for p in self.local["packages"]}
        self.new = {key(p): p for p in self.target["packages"]}
        self.delta = dependency_difference(self.local, self.target)
        self.recheck()

    def recheck(self) -> None:
        self.check_cancelled()
        for item in [
            self.manifest["code"],
            *(self.new[k]["artifact"] for k in self.delta["install"]),
        ]:
            path = safe_destination(self.work, item["filename"])
            if path.is_symlink() or digest(path) != item["sha256"]:
                raise DependencyInstallError("DIGEST_MISMATCH")

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise DependencyInstallError("CONTAINER_STOPPED")

    def synchronize_code(self) -> None:
        protected = (
            set(self.local["node_scopes"])
            | {p["path"] for p in self.local["node_links"]}
            | {".initialized"}
        )

        def clean(directory: Path) -> None:
            for path in directory.iterdir():
                relative = path.relative_to(self.runtime).as_posix()
                if relative in protected:
                    continue
                if any(p.startswith(relative + "/") for p in protected):
                    if path.is_symlink() or not path.is_dir():
                        raise DependencyInstallError("UNSAFE_STORAGE")
                    clean(path)
                elif path.is_symlink() or not path.is_dir():
                    path.unlink()
                else:
                    shutil.rmtree(path)

        clean(self.runtime)
        shutil.copytree(
            self.work / "app", self.runtime, symlinks=True, dirs_exist_ok=True
        )

    def run_uv(self, operation: str, arguments: list[str]) -> None:
        self.check_cancelled()
        environment = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("UV_", "PIP_", "PYTHON")) and k != "VIRTUAL_ENV"
        }
        command = [
            self.uv,
            "--offline",
            "--no-cache",
            "--no-config",
            "--no-python-downloads",
            "pip",
            operation,
            "--python",
            str(self.python),
            *arguments,
        ]
        log = self.storage / "update-tmp/installation.log"
        output = None
        try:
            output = os.fdopen(
                os.open(
                    log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600
                ),
                "a",
            )
            output.write(
                "dependency_operation="
                + operation
                + " packages="
                + json.dumps([Path(x).name for x in arguments])
                + "\n"
            )
            output.flush()
        except OSError:
            if output is not None:
                try:
                    output.close()
                except OSError:
                    pass  # The open/write failure is reported below.
                output = None
            update_warning("INSTALL_LOG_UNAVAILABLE")
        try:
            result = subprocess.run(
                command, env=environment, stdout=output, stderr=output, check=False
            )
        finally:
            if output is not None:
                try:
                    output.close()
                except OSError:
                    update_warning("INSTALL_LOG_UNAVAILABLE")
        self.check_cancelled()
        if result.returncode:
            raise DependencyInstallError("DEPENDENCY_OPERATION_FAILED")

    def log_node(self, operation: str, package: dict) -> None:
        try:
            with os.fdopen(
                os.open(
                    self.storage / "update-tmp/installation.log",
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                ),
                "a",
            ) as output:
                output.write(
                    f"dependency_operation=node_{operation} instance={package['location']} version={package['version']}\n"
                )
        except OSError:
            update_warning("INSTALL_LOG_UNAVAILABLE")

    def apply(self) -> None:
        self.check_cancelled()
        removed = sorted(
            set(self.delta["remove"]) | (set(self.delta["install"]) & self.old.keys())
        )
        python_remove = [
            self.old[k]["name"] for k in removed if self.old[k]["ecosystem"] == "python"
        ]
        if python_remove:
            self.run_uv("uninstall", python_remove)
        for k in self.delta["install"]:
            package = self.new[k]
            if package["ecosystem"] == "python":
                self.run_uv(
                    "install",
                    [
                        "--no-index",
                        "--no-deps",
                        "--no-build",
                        str(self.work / package["artifact"]["filename"]),
                    ],
                )
        # Only ancestors of removed leaves may become obsolete layout.
        directories: set[Path] = set()

        def remove_leaf(name: str) -> None:
            path = safe_destination(self.runtime, name)
            path.unlink()
            for parent in path.parents:
                if (
                    parent == self.runtime
                    or "node_modules" not in parent.relative_to(self.runtime).parts
                ):
                    break
                directories.add(parent)

        # Remove owned leaves only. Never rmtree a package containing kept children.
        for k in removed:
            package = self.old[k]
            if package["ecosystem"] == "node":
                self.log_node("remove", package)
                for name in package["files"]:
                    self.check_cancelled()
                    remove_leaf(name)
        old_links = {x["path"]: x["target"] for x in self.local["node_links"]}
        new_links = {x["path"]: x["target"] for x in self.target["node_links"]}
        for name, target in old_links.items():
            path = safe_destination(self.runtime, name)
            if new_links.get(name) != target and path.is_symlink():
                remove_leaf(name)
        # Vacate old directories before file/link type transitions. Nonempty parents
        # retain their kept nested instances; unrelated empty directories are untouched.
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            relative = path.relative_to(self.runtime).as_posix()
            if relative in self.target["node_scopes"]:
                continue
            safe_destination(self.runtime, relative)
            if path.is_symlink():
                raise DependencyInstallError("UNSAFE_STORAGE")
            try:
                path.rmdir()
            except OSError as error:
                if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise
        for k in self.delta["install"]:
            package = self.new[k]
            if package["ecosystem"] != "node":
                continue
            self.log_node("install", package)
            with tarfile.open(
                self.work / package["artifact"]["filename"], "r:"
            ) as archive:
                for member in archive:
                    self.check_cancelled()
                    path = safe_destination(self.runtime, member.name)
                    if member.name not in package["files"]:
                        raise DependencyInstallError("UNSAFE_ARCHIVE")
                    if member.issym():
                        continue  # Lay out all links after regular files.
                    if not member.isfile():
                        raise DependencyInstallError("UNSAFE_ARCHIVE")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stream = archive.extractfile(member)
                    with stream, path.open("xb") as output:
                        shutil.copyfileobj(stream, output)
                    path.chmod(member.mode & 0o777)
        for name, target in new_links.items():
            path = safe_destination(self.runtime, name)
            if path.is_symlink() and os.readlink(path) == target:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        for scope in self.target["node_scopes"]:
            safe_destination(self.runtime, scope).mkdir(parents=True, exist_ok=True)
        # Record the installed target; successful startup, not a second identity
        # scan or import probe, determines installation success.
        from shuku_dependencies.records import installed_records

        changed = {
            self.new[k]["name"]
            for k in self.delta["install"]
            if k.startswith("python:")
        }
        kept_records = [
            r
            for r in self.local.get("python_records", [])
            if "python:" + r["name"] in self.delta["keep"]
        ]
        try:
            changed_records = installed_records(
                self.storage / "dependencies/python",
                verify_contents=False,
                names=changed,
            )
            self.result = {
                **self.target,
                "python_records": sorted(
                    kept_records + changed_records, key=lambda record: record["name"]
                ),
            }
        except (OSError, ValueError, KeyError, TypeError):
            update_warning("INSTALLATION_RECORD_UNAVAILABLE")
