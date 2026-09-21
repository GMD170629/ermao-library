"""Fixed, offline installation operations. Standard library; no runtime imports."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dependency_install import DependencyInstallation, update_warning


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
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise InstallError("INVALID_STATE")
    return value


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


def retire_previous_installation(storage: Path) -> bool:
    """Retire old requests; failure disables consumption, never application startup."""
    root = storage / "update-tmp"
    try:
        with os.fdopen(
            os.open(
                root / "prepare.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            ),
            "w",
        ) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = root / "install-request.json"
            if request.exists() or request.is_symlink():
                request.replace(root / "install-request.json.previous")
            try:
                state = read_json(root / "preparation.json")
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
                    write_json(root / "preparation.json", state)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, KeyError, InstallError):
                update_warning("PREVIOUS_STATE_UNAVAILABLE")
        return True
    except OSError:
        update_warning("PREVIOUS_REQUEST_NOT_RETIRED")
        return False


class Installation:
    def __init__(self, storage: Path):
        self.storage = storage
        self.root = storage / "update-tmp"
        self.runtime = storage / "runtime"
        self.lock = None
        self.state = None
        self.dependencies = None
        self.cancelled = lambda: False
        self.reserved = False
        self.replacing = False

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
        if (self.root / "installation-incomplete").exists() or (
            self.root / "installation-incomplete"
        ).is_symlink():
            raise InstallError("INSTALLATION_RECORD_UNAVAILABLE")
        try:
            descriptor = os.open(
                self.root / "installation.log",
                os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
            )
            os.close(descriptor)
        except OSError:
            update_warning("INSTALL_LOG_UNAVAILABLE")
        self.phase("checking")
        return True

    def phase(self, phase: str, error: str | None = None) -> None:
        assert self.state is not None
        if error:
            self.state["failed_phase"] = self.state["phase"]
        self.state.update(
            phase=phase, error=error, updated_at=datetime.now(timezone.utc).isoformat()
        )
        try:
            write_json(self.root / "preparation.json", self.state)
        except OSError:
            update_warning("INSTALL_STATE_WRITE_FAILED")
        message = f"application_update phase={phase} reason={error or 'none'}"
        print(message, flush=True)
        try:
            with os.fdopen(
                os.open(
                    self.root / "installation.log",
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                ),
                "a",
            ) as stream:
                stream.write(self.state["updated_at"] + " " + message + "\n")
        except OSError:
            update_warning("INSTALL_LOG_UNAVAILABLE")

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
        if self.root.is_symlink() or (self.root / "prepared").is_symlink():
            raise InstallError("UNSAFE_STORAGE")

    def reserve(self) -> None:
        # Required control record is created while the old application is still running.
        write_json(
            self.root / "installation-incomplete", {"target": self.state["target"]}
        )
        self.reserved = True

    def verify_dependencies(self) -> None:
        if self.state["target"].get("format", 1) == 2:
            self.dependencies = DependencyInstallation(
                self.storage,
                read_json(self.root / "install-request.json"),
                self.state,
                Path(__file__).with_name("environment.json"),
                cancelled=self.cancelled,
            )

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
        if not self.reserved:
            raise InstallError("INSTALLATION_NOT_RESERVED")
        self.replacing = True
        self.phase("copying")
        if self.dependencies is not None:
            self.dependencies.check_cancelled()
            self.dependencies.synchronize_code()
            self.dependencies.apply()
            return
        replace_runtime(source, self.runtime)

    def success(self) -> None:
        recorded = True
        if self.dependencies is not None:
            if self.dependencies.result is None:
                recorded = False
                update_warning("INSTALLATION_RECORD_UNAVAILABLE")
            else:
                try:
                    write_json(
                        self.storage / "dependencies/installed.json",
                        self.dependencies.result,
                    )
                except OSError:
                    recorded = False
                    update_warning("INSTALLATION_RECORD_UNAVAILABLE")
        self.phase("applied")
        for name in (["installation-incomplete"] if recorded else []) + [
            "install-request.json"
        ]:
            try:
                (self.root / name).unlink(missing_ok=True)
            except OSError:
                update_warning("INSTALL_CLEANUP_FAILED")
        self.close()

    def fail(self, code: str) -> None:
        self.phase("failed", code)
        if self.reserved and not self.replacing:
            try:
                (self.root / "installation-incomplete").unlink(missing_ok=True)
            except OSError:
                update_warning("INSTALL_CLEANUP_FAILED")
        # Keep reservation on any failure: never silently retry on startup.
        self.close()

    def close(self) -> None:
        if self.lock:
            self.lock.close()
            self.lock = None
