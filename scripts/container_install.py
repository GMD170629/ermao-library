"""Fixed, offline installation operations. Standard library; no runtime imports."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from dependency_install import DependencyInstallation


class InstallError(RuntimeError):
    pass


REQUIRED_RUNTIME_FILES = (
    "scripts/start-unified-app.sh",
    "scripts/unified-http-gateway.mjs",
    "apps/web/server.js",
    "apps/api-python/app/bootstrap/prestart.py",
)


def replace_runtime(source: Path, runtime: Path) -> None:
    """Caller owns validation and the incomplete marker; never follow old links."""
    runtime.mkdir(exist_ok=True)
    for path in runtime.iterdir():
        if path.name == ".initialized":
            continue
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)
    shutil.copytree(source, runtime, symlinks=True, dirs_exist_ok=True)


def read_json(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 16384:
        raise InstallError("INVALID_STATE")
    return json.loads(path.read_bytes())


def write_json(path: Path, value: dict) -> None:
    fd = os.open(
        path.with_suffix(".tmp"),
        os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(path.with_suffix(".tmp"), path)


def retire_previous_installation(storage: Path) -> None:
    """Keep restart diagnostics without replaying a previous install request."""
    root = storage / "update-tmp"
    with os.fdopen(
        os.open(root / "prepare.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600),
        "w",
    ) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in ("install-request.json", "installation-incomplete"):
            path = root / name
            if path.exists() or path.is_symlink():
                path.replace(root / (name + ".previous"))
        path = root / "preparation.json"
        try:
            state = read_json(path)
        except (OSError, ValueError, InstallError) as error:
            if not isinstance(error, FileNotFoundError):
                print(
                    "previous update state could not be read / 无法读取上次更新状态",
                    flush=True,
                )
            return
        if isinstance(state, dict) and state.get("phase") in {
            "requested",
            "checking",
            "stopping",
            "backup",
            "copying",
            "starting",
        }:
            state.update(
                failed_phase=state["phase"],
                phase="failed",
                error="CONTAINER_RESTARTED",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            write_json(path, state)


class Installation:
    def __init__(self, storage: Path):
        self.storage = storage
        self.root = storage / "update-tmp"
        self.runtime = storage / "runtime"
        self.lock = None
        self.state = None
        self.dependencies = None
        self.cancelled = lambda: False

    def claim(self) -> bool:
        request = self.root / "install-request.json"
        if not request.exists():
            return False
        lock = os.fdopen(
            os.open(
                self.root / "prepare.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            ),
            "w",
        )
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return False
        self.lock = lock
        self.state = read_json(self.root / "preparation.json")
        requested_target = read_json(request)["target"]
        if self.state["phase"] != "requested" or any(
            self.state["target"].get(key) != requested_target.get(key)
            for key in ("version", "sha256", "format")
        ):
            raise InstallError("INVALID_INSTALL_REQUEST")
        self.reject_package_protocol()
        log_fd = os.open(
            self.root / "installation.log",
            os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        os.close(log_fd)
        self.phase("checking")
        return True

    def phase(self, phase: str, error: str | None = None) -> None:
        assert self.state is not None
        if error:
            self.state["failed_phase"] = self.state["phase"]
        self.state.update(
            phase=phase, error=error, updated_at=datetime.now(timezone.utc).isoformat()
        )
        write_json(self.root / "preparation.json", self.state)
        message = f"application_update phase={phase} reason={error or 'none'}"
        print(message, flush=True)
        log_fd = os.open(
            self.root / "installation.log",
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(log_fd, "a") as stream:
            stream.write(self.state["updated_at"] + " " + message + "\n")

    def reject_package_protocol(self) -> None:
        target = self.state["target"] if self.state else {}
        identity = self.runtime / "application.json"
        protocol = target.get("format", 1)
        if protocol not in (1, 2) or (
            identity.is_file() and read_json(identity).get("protocol", 1) != protocol
        ):
            raise InstallError("UNSUPPORTED_UPDATE_PROTOCOL")

    def check_paths(self) -> None:
        self.reject_package_protocol()
        if (
            self.runtime.is_symlink()
            or self.runtime.resolve() != self.storage / "runtime"
        ):
            raise InstallError("UNSAFE_RUNTIME")
        if (
            not (self.runtime / ".initialized").is_file()
            or (self.runtime / ".initialized").is_symlink()
        ):
            raise InstallError("UNINITIALIZED_RUNTIME")
        if self.root.is_symlink() or (self.root / "prepared").is_symlink():
            raise InstallError("UNSAFE_STORAGE")
        if not os.access(self.runtime, os.W_OK | os.X_OK):
            raise InstallError("RUNTIME_NOT_WRITABLE")

    def verify_dependencies(self) -> None:
        if self.state["target"].get("format", 1) == 2:
            self.dependencies = DependencyInstallation(
                self.storage,
                read_json(self.root / "install-request.json"),
                self.state,
                Path(__file__).with_name("environment.json"),
                cancelled=self.cancelled,
            )

    def backup(self) -> None:
        self.verify_dependencies()
        self.phase("backup")
        backup_database(self.storage, self.root / "database-before-update.sqlite3")

    def synchronize(self) -> None:
        self.check_paths()
        if self.state["target"].get("format", 1) == 2 and self.dependencies is None:
            raise InstallError("PLAN_NOT_VERIFIED")
        source = self.root / "prepared/app"
        if source.is_symlink() or not source.is_dir():
            raise InstallError("UNSAFE_SOURCE")
        identity = source / "application.json"
        if identity.is_file() and read_json(identity).get("protocol", 1) != self.state[
            "target"
        ].get("format", 1):
            raise InstallError("UNSUPPORTED_UPDATE_PROTOCOL")
        if self.dependencies is not None:
            self.dependencies.recheck()
        # Old processes are gone. Remove entries without following target links,
        # then copy the already validated tree; .initialized is launcher-owned.
        write_json(
            self.root / "installation-incomplete", {"target": self.state["target"]}
        )
        self.phase("copying")
        if self.dependencies is not None:
            self.dependencies.check_cancelled()
            self.dependencies.synchronize_code()
            self.dependencies.apply()
            return
        replace_runtime(source, self.runtime)

    def success(self) -> None:
        if self.dependencies is not None:
            if self.dependencies.result is None:
                raise InstallError("DEPENDENCIES_NOT_VERIFIED")
            from shuku_dependencies.installed import collect_target

            actual = collect_target(self.storage, self.dependencies.target)
            if actual != self.dependencies.result:
                raise InstallError("DEPENDENCIES_CHANGED_DURING_STARTUP")
            write_json(self.storage / "dependencies/installed.json", actual)
        self.phase("success")
        (self.root / "installation-incomplete").unlink()
        (self.root / "install-request.json").unlink()
        self.close()

    def fail(self, code: str) -> None:
        self.phase("failed", code)
        # Keep reservation on any failure: never silently retry on startup.
        self.close()

    def close(self) -> None:
        if self.lock:
            self.lock.close()
            self.lock = None


def backup_database(storage: Path, destination: Path) -> None:
    database = storage / "database/shuku.sqlite3"
    backup = destination
    if database.is_symlink() or database.parent.is_symlink() or backup.is_symlink():
        raise InstallError("UNSAFE_DATABASE")
    # SQLite's native backup API takes a consistent snapshot including WAL.
    # No schema queries, migrations, logical exports or application imports.
    deadline = time.monotonic() + 60

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise InstallError("BACKUP_TIMEOUT")

    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        backup.unlink(missing_ok=True)
        os.close(
            os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        )
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target, pages=256, progress=progress)
