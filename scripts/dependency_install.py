"""Fixed protocol 2 executor. Standard library only; never imports runtime code."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from dependency_packages import canonical_digest, digest
from shuku_dependencies.installed import (
    bounded_json,
    collect_target,
    verify_current,
    wheel_destination,
)
from shuku_dependencies.packages import dependency_difference
from shuku_dependencies.packages import dependency_key as key


class DependencyInstallError(RuntimeError):
    pass


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
        if (
            manifest_path.stat().st_size != target["size"]
            or digest(manifest_path) != target["sha256"]
        ):
            raise DependencyInstallError("DIGEST_MISMATCH")
        self.plan = bounded_json(self.work / "plan.json", 32 * 1024 * 1024)
        plan_sha = self.request.get("plan_sha256")
        if (
            not plan_sha
            or canonical_digest(self.plan) != plan_sha
            or self.state["summary"]["plan_sha256"] != plan_sha
        ):
            raise DependencyInstallError("PLAN_CHANGED")
        fixed = bounded_json(self.fixed)
        current = bounded_json(self.runtime / "application.json")
        if (
            target["format"] != 2
            or current.get("protocol") != 2
            or self.manifest["protocol"] != 2
            or self.manifest["environment"] != fixed["environment"]
            or target["environment"] != fixed["environment"]
            or self.manifest["python_abi"] != fixed["inventory"]["abi"]
            or self.manifest["version"] != target["version"]
            or self.plan["manifest_sha256"] != target["sha256"]
            or self.plan["version"] != target["version"]
        ):
            raise DependencyInstallError("INCOMPATIBLE_ENVIRONMENT")
        version = lambda v: tuple(map(int, v.split(".")))
        if current["version"] != self.request["current"] or version(
            target["version"]
        ) <= version(current["version"]):
            raise DependencyInstallError("NOT_NEWER")
        self.local = bounded_json(self.storage / "dependencies/installed.json")
        self.target = self.manifest["dependencies"]
        self.old = {key(p): p for p in self.local["packages"]}
        self.new = {key(p): p for p in self.target["packages"]}
        self.delta = dependency_difference(self.local, self.target)
        if (
            self.delta != self.plan["difference"]
            or self.plan["dependency_identity"] != self.target["identity"]
        ):
            raise DependencyInstallError("PLAN_CHANGED")
        self.recheck()

    def recheck(self) -> None:
        self.check_cancelled()
        try:
            baseline = verify_current(self.storage, self.local)
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise DependencyInstallError("LOCAL_RECORDS_DRIFT") from error
        if baseline != self.plan["baseline"]:
            raise DependencyInstallError("LOCAL_RECORDS_DRIFT")
        for item in [
            self.manifest["code"],
            *(self.new[k]["artifact"] for k in self.delta["install"]),
        ]:
            path = safe_destination(self.work, item["filename"])
            if (
                path.is_symlink()
                or path.stat().st_size != item["size"]
                or digest(path) != item["sha256"]
            ):
                raise DependencyInstallError("DIGEST_MISMATCH")
        required = (
            self.manifest["code"]["expanded_size"] * 2
            + self.manifest["dependency_expanded_size"]
        )
        database = self.storage / "database/shuku.sqlite3"
        if database.exists():
            required += database.stat().st_size * 2
        if shutil.disk_usage(self.storage).free < required + 64 * 1024 * 1024:
            raise DependencyInstallError("INSUFFICIENT_SPACE")
        for root in (self.runtime, self.storage / "dependencies/python", self.work):
            for directory, dirs, files in os.walk(root, followlinks=False):
                if not os.access(directory, os.W_OK | os.X_OK):
                    raise DependencyInstallError("STORAGE_NOT_WRITABLE")

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise DependencyInstallError("CONTAINER_STOPPED")

    def verify_code(self) -> None:
        """The business preflight re-extracts; bind that tree to the confirmed archive."""
        root = self.work / "app"
        seen = set()
        with tarfile.open(
            self.work / self.manifest["code"]["filename"], "r:gz"
        ) as archive:
            for member in archive:
                path = safe_destination(root, member.name)
                seen.add(member.name)
                if member.isdir():
                    valid = path.is_dir() and not path.is_symlink()
                elif member.issym():
                    valid = path.is_symlink() and os.readlink(path) == member.linkname
                elif member.isfile() or member.islnk():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise DependencyInstallError("INVALID_ARCHIVE")
                    with stream:
                        expected = hashlib.file_digest(stream, "sha256").hexdigest()
                    valid = (
                        not path.is_symlink()
                        and path.is_file()
                        and digest(path) == expected
                    )
                else:
                    valid = False
                if not valid:
                    raise DependencyInstallError("PREPARED_CODE_CHANGED")
        if any(p.relative_to(root).as_posix() not in seen for p in root.rglob("*")):
            raise DependencyInstallError("PREPARED_CODE_CHANGED")

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
        with log.open("a") as output:
            output.write(
                "dependency_operation="
                + operation
                + " packages="
                + json.dumps([Path(x).name for x in arguments])
                + "\n"
            )
            output.flush()
            result = subprocess.run(
                command, env=environment, stdout=output, stderr=output, check=False
            )
        self.check_cancelled()
        if result.returncode:
            raise DependencyInstallError("DEPENDENCY_OPERATION_FAILED")

    def log_node(self, operation: str, package: dict) -> None:
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
        # Remove owned leaves only. Never rmtree a package containing kept children.
        for k in removed:
            package = self.old[k]
            if package["ecosystem"] == "node":
                self.log_node("remove", package)
                for name in package["files"]:
                    self.check_cancelled()
                    safe_destination(self.runtime, name).unlink()
        old_links = {x["path"]: x["target"] for x in self.local["node_links"]}
        new_links = {x["path"]: x["target"] for x in self.target["node_links"]}
        for name, target in old_links.items():
            path = safe_destination(self.runtime, name)
            if new_links.get(name) != target and path.is_symlink():
                path.unlink()
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
        # Empty obsolete directories are layout, not package contents.
        for directory, dirs, files in os.walk(
            self.runtime, topdown=False, followlinks=False
        ):
            path = Path(directory)
            relative = path.relative_to(self.runtime).as_posix()
            if (
                "node_modules" in path.relative_to(self.runtime).parts
                and relative not in self.target["node_scopes"]
            ):
                try:
                    path.rmdir()
                except OSError:
                    pass  # Nonempty directories (including kept nested packages) remain.
        for scope in self.target["node_scopes"]:
            safe_destination(self.runtime, scope).mkdir(parents=True, exist_ok=True)
        self.result = collect_target(self.storage, self.target)
        old_records = {r["name"]: r for r in self.local["python_records"]}
        new_records = {r["name"]: r for r in self.result["python_records"]}
        for k in self.delta["keep"]:
            if k.startswith("python:") and old_records[k[7:]] != new_records[k[7:]]:
                raise DependencyInstallError("KEEP_DEPENDENCY_CHANGED")
        self.verify_wheel_contents()
        self.run_uv("check", [])
        self.check_imports()

    def check_imports(self) -> None:
        self.check_cancelled()
        environment = {
            k: v
            for k, v in os.environ.items()
            if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
        }
        environment["PYTHONNOUSERSITE"] = "1"
        with (self.storage / "update-tmp/installation.log").open("a") as output:
            result = subprocess.run(
                [
                    str(self.python),
                    "-c",
                    "import fastapi, uvicorn, sqlalchemy, alembic; import app.main, app.worker.main",
                ],
                cwd=self.runtime / "apps/api-python",
                env=environment,
                stdout=output,
                stderr=output,
                check=False,
            )
        if result.returncode:
            raise DependencyInstallError("DEPENDENCY_IMPORT_FAILED")
        self.check_cancelled()

    def verify_wheel_contents(self) -> None:
        prefix = self.storage / "dependencies/python"
        for k in self.delta["install"]:
            p = self.new[k]
            if p["ecosystem"] != "python":
                continue
            with zipfile.ZipFile(self.work / p["artifact"]["filename"]) as wheel:
                for name in p["files"]:
                    if name.endswith(".dist-info/RECORD"):
                        continue  # Installer rewrites RECORD and generated scripts.
                    parts = name.split("/")
                    path = wheel_destination(prefix, p["name"], name)
                    expected = wheel.read(name)
                    actual = path.read_bytes()
                    if (
                        expected.startswith((b"#!python\n", b"#!pythonw\n"))
                        and parts[0].endswith(".data")
                        and parts[1] == "scripts"
                    ):
                        expected = expected.split(b"\n", 1)[1]
                        actual = actual.split(b"\n", 1)[1]
                    if actual != expected:
                        raise DependencyInstallError("INSTALLED_ARTIFACT_MISMATCH")
