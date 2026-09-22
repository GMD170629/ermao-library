#!/usr/bin/env python3
"""Fixed container entry. Standard library only; never import runtime code."""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from container_image import ImageSynchronization
from container_install import (
    Installation,
    InstallError,
    retire_previous_installation,
    update_warning,
    write_json,
)
from dependency_environment import (
    DependencyError,
    business_environment,
    initialize_dependencies,
)
from dependency_install import DependencyInstallError


class StartupError(RuntimeError):
    pass


def initialize_runtime(seed: Path, runtime: Path) -> None:
    """Reuse existing runtime; the application owns its startup requirements."""
    if runtime.is_symlink() or (runtime.exists() and not runtime.is_dir()):
        raise StartupError("runtime must be a directory / 程序路径必须是目录")
    if not runtime.exists():
        shutil.copytree(seed, runtime, symlinks=True)
    marker = runtime / ".initialized"
    try:
        if not marker.exists() and not marker.is_symlink():
            marker.write_text("1\n", encoding="utf-8")
    except OSError as error:
        update_warning("INITIALIZATION_RECORD_WRITE_FAILED", error)


def run_application(runtime: Path, storage: Path, allow_updates: bool = True) -> int:
    stop_signal = 0

    def stop(signum: int, _frame: object) -> None:
        nonlocal stop_signal
        stop_signal = stop_signal or signum

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            error_number = ctypes.get_errno()
            raise StartupError(
                "cannot enable child reaping / 无法启用子进程回收"
            ) from OSError(error_number, os.strerror(error_number))

    environment = {
        **business_environment(storage),
        "STORAGE_ROOT": str(storage),
        "ROOT_DIR": str(runtime),
        "PYTHON_API_DIR": str(runtime / "apps/api-python"),
        "NEXT_SERVER": str(runtime / "apps/web/server.js"),
        "GATEWAY_SERVER": str(runtime / "scripts/unified-http-gateway.mjs"),
    }
    installer = Installation(storage)
    installer.cancelled = lambda: bool(stop_signal)
    child = None
    forwarded = False
    preflight = None
    installing = False
    stopped = False
    deadline = 0.0

    def launch() -> subprocess.Popen:
        return subprocess.Popen(
            ["sh", str(runtime / "scripts/start-unified-app.sh")],
            cwd=runtime,
            env={
                **environment,
                "IMPORT_WORKER_READY_FILE": str(storage / "update-tmp/worker-ready"),
            },
            start_new_session=True,
        )

    def fail(code: str) -> None:
        nonlocal installing
        installer.fail(code)
        installing = False

    child = launch()
    while True:
        if stop_signal and not forwarded:
            if installing:
                fail("CONTAINER_STOPPED")
            if child.returncode is None:
                os.kill(child.pid, stop_signal)
            if preflight is not None and preflight.returncode is None:
                os.kill(preflight.pid, stop_signal)
            forwarded = True
        # Sole owner of all child statuses, including the main Popen child.
        empty = False
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                # diagnostics-control-flow: ECHILD is the waitpid proof that all children were reaped.
                empty = True
                break
            if pid == child.pid:
                child.returncode = os.waitstatus_to_exitcode(status)
            if preflight is not None and pid == preflight.pid:
                preflight.returncode = os.waitstatus_to_exitcode(status)
            if pid == 0:
                break
        if installing and installer.state["phase"] == "checking":
            if child.returncode is not None or time.monotonic() >= deadline:
                if preflight is not None and preflight.returncode is None:
                    os.kill(preflight.pid, signal.SIGTERM)
                fail("PREFLIGHT_INTERRUPTED")
            elif preflight.returncode is not None:
                if preflight.returncode != 0:
                    update_warning(
                        "PREFLIGHT_FAILED",
                        subprocess.CalledProcessError(
                            preflight.returncode,
                            ["python", "-m", "app.bootstrap.update_install"],
                        ),
                        stage="preflight_process",
                    )
                    fail("PREFLIGHT_FAILED")
                else:
                    try:
                        installer.verify_dependencies()
                        installer.reserve()
                    except Exception as error:  # noqa: BLE001 - owned preflight boundary
                        update_warning(
                            "PREFLIGHT_FAILED", error, stage="verify_and_reserve"
                        )
                        fail(
                            str(error)
                            if isinstance(error, (InstallError, DependencyInstallError))
                            else "PREFLIGHT_FAILED"
                        )
                        continue
                    installer.phase("stopping")
                    os.kill(child.pid, signal.SIGUSR1)
                    deadline = time.monotonic() + 120
        elif installing and installer.state["phase"] == "stopping":
            # ECHILD also proves adopted tools (including separate sessions) exited.
            if child.returncode is not None and empty:
                stopped = True
                try:
                    if child.returncode != 0:
                        raise InstallError(
                            "STOP_FAILED"
                        ) from subprocess.CalledProcessError(
                            child.returncode, ["start-unified-app"]
                        )
                    installer.verify_dependencies()
                    if stop_signal:
                        raise InstallError("CONTAINER_STOPPED")
                    installer.synchronize()
                    if stop_signal:
                        raise InstallError("CONTAINER_STOPPED")
                    installer.phase("starting")
                    child = launch()
                    installer.success()
                    installing = False
                    stopped = False
                    allow_updates = not any(
                        (installer.root / name).exists()
                        or (installer.root / name).is_symlink()
                        for name in ("install-request.json", "installation-incomplete")
                    )
                    if allow_updates:
                        installer = Installation(storage)
                        installer.cancelled = lambda: bool(stop_signal)
                except Exception as error:  # noqa: BLE001 - owned installation boundary
                    update_warning(
                        "INSTALLATION_FAILED", error, stage=installer.state["phase"]
                    )
                    fail(
                        str(error)
                        if isinstance(error, (InstallError, DependencyInstallError))
                        else "INSTALLATION_FAILED"
                    )
                    return 128 + stop_signal if stop_signal else 1
            elif time.monotonic() >= deadline:
                fail("STOP_TIMEOUT")
                # No kill or restart: retain the old process group until it exits
                # or the administrator stops the container.
        elif (  # noqa: SIM102
            not stop_signal
            and allow_updates
            and child.returncode is None
            and installer.lock is None
            and not stopped
        ):
            # A failed reservation is never retried during this run.
            if installer.state is None:
                try:
                    if installer.claim():
                        installing = True
                        installer.check_paths()
                        preflight = subprocess.Popen(
                            [
                                environment["SHUKU_BUSINESS_PYTHON"],
                                "-m",
                                "app.bootstrap.update_install",
                            ],
                            cwd=runtime / "apps/api-python",
                            env=environment,
                            start_new_session=True,
                        )
                        deadline = time.monotonic() + 300
                except Exception as error:  # noqa: BLE001 - isolate rejected installation requests.
                    update_warning(
                        "INSTALL_REQUEST_FAILED", error, stage="claim_and_preflight"
                    )
                    if installer.state is not None:
                        fail(
                            str(error)
                            if isinstance(error, (InstallError, DependencyInstallError))
                            else "PREFLIGHT_FAILED"
                        )
                    else:
                        installer.close()
                        allow_updates = False
        if child.returncode is not None and not installing:
            if empty:
                break
            # Ordinary termination retains the established orphan cleanup. An
            # installation failure must not kill remaining tools and then copy.
            if installer.state is None or stop_signal:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    # diagnostics-control-flow: process group exited between waitpid and orphan cleanup.
                    pass
        time.sleep(0.2)
    return (
        128 + stop_signal
        if stop_signal
        else (child.returncode or (1 if stopped else 0))
    )


def convert_legacy(
    seed: Path, runtime: Path, storage: Path, dependency_seed: Path
) -> None:
    """Known v1 layout only, same release/lock; caller holds the stopped launcher lock."""
    from dependency_packages import node_packages

    if runtime.is_symlink() or not (runtime / ".initialized").is_file():
        raise StartupError("unknown legacy layout / 未知旧布局")
    for relative in (
        "application.json",
        "scripts/start-unified-app.sh",
        "apps/api-python/uv.lock",
    ):
        path = runtime / relative
        if path.is_symlink() or not path.resolve().is_relative_to(runtime.resolve()):
            raise StartupError("unsafe legacy layout / 旧布局路径不安全")
    current = json.loads((runtime / "application.json").read_text())
    target = json.loads((seed / "application.json").read_text())
    if current.get("protocol", 1) != 1 or target.get("protocol") != 2:
        raise StartupError("unsupported conversion / 不支持此转换")
    # Conversion is not an application update: require the exact release and lock.
    if (
        current["environment"]["platform"] != target["environment"]["platform"]
        or current["version"] != target["version"]
        or (runtime / "apps/api-python/uv.lock").read_bytes()
        != (seed / "apps/api-python/uv.lock").read_bytes()
    ):
        raise StartupError(
            "conversion requires the same release and lock / 转换要求程序版本和锁文件相同"
        )
    if (storage / "dependencies").exists():
        raise StartupError(
            "conversion dependencies already exist; inspect manually / 转换依赖已存在，请人工检查"
        )
    initialize_runtime(seed, runtime)
    with tempfile.TemporaryDirectory(dir=storage / "update-tmp") as temporary:
        from dataclasses import asdict

        actual, links, scopes = node_packages(runtime, Path(temporary))
        manifest = json.loads((dependency_seed / "manifest.json").read_text())
        if (
            [asdict(item) for item in actual]
            != [
                dict(item, files=tuple(item["files"]))
                for item in manifest["packages"]
                if item["ecosystem"] == "node"
            ]
            or links != manifest["node_links"]
            or scopes != manifest["node_scopes"]
        ):
            raise StartupError(
                "legacy Node layout differs from seed / 旧 Node 布局与种子不一致"
            )
    initialize_dependencies(storage, dependency_seed)
    # No application replacement and no v2 package installation. Only the known launch script changes.
    script = runtime / "scripts/start-unified-app.sh"
    staged = script.with_suffix(".conversion")
    descriptor = os.open(
        staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o755
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write((seed / "scripts/start-unified-app.sh").read_bytes())
        output.flush()
        os.fsync(output.fileno())
    os.replace(staged, script)
    write_json(
        runtime / "application.json",
        {**current, "environment": target["environment"], "protocol": 2},
    )
    print("dependency conversion complete / 依赖转换完成", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--convert-legacy",
        action="store_true",
        help="convert a stopped same-release v1 deployment / 转换已停机的同版本旧部署",
    )
    args = parser.parse_args()

    def stop_initialization(signum: int, _frame: object) -> None:
        print("startup cancelled / 启动已取消", flush=True)
        raise SystemExit(128 + signum)

    # PID 1 must also honor container stop while copying the initial program.
    signal.signal(signal.SIGTERM, stop_initialization)
    signal.signal(signal.SIGINT, stop_initialization)
    storage = Path(os.environ.get("STORAGE_ROOT", "/app/storage")).resolve()
    seed = Path(os.environ.get("SHUKU_IMAGE_ROOT", "/opt/shuku-image")).resolve()
    runtime = storage / "runtime"
    state = storage / "update-tmp"
    image_sync = None
    try:
        if state.is_symlink():
            raise StartupError("update-tmp must not be a link / 更新临时目录不能是链接")
        if (
            storage == seed
            or storage.is_relative_to(seed)
            or seed.is_relative_to(storage)
        ):
            raise StartupError(
                "image and storage must be separate / 镜像程序与数据必须分离"
            )
        state.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(
            state / "launcher.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(lock_fd, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # diagnostics-control-flow: lock contention means an existing launcher owns startup.
                raise StartupError(
                    "application is already running / 应用已在运行"
                ) from None
            allow_updates = retire_previous_installation(storage)
            dependency_seed = Path(
                os.environ.get("SHUKU_DEPENDENCY_SEED", "/opt/shuku-dependency-seed")
            )
            if args.convert_legacy:
                # Also exclude an in-progress preparation, using its existing lock.
                with os.fdopen(
                    os.open(
                        state / "prepare.lock",
                        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                        0o600,
                    ),
                    "w",
                ) as preparation_lock:
                    fcntl.flock(preparation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    convert_legacy(seed, runtime, storage, dependency_seed)
                return 0
            image_sync = ImageSynchronization(storage, seed, dependency_seed)
            pending_image = image_sync.prepare()
            if pending_image:
                image_sync.success()
            initialize_runtime(seed, runtime)
            initialize_dependencies(storage, dependency_seed)
            print("runtime ready / 持久化程序目录就绪", flush=True)
            return run_application(runtime, storage, allow_updates)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        shutil.Error,
        StartupError,
        DependencyError,
        InstallError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
    ) as error:
        update_warning("CONTAINER_STARTUP_FAILED", error, stage="startup")
        return 1
    finally:
        if image_sync is not None:
            image_sync.close()


if __name__ == "__main__":
    sys.exit(main())
