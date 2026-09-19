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
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from container_install import Installation, InstallError, backup_database, write_json
from dependency_environment import (
    DependencyError,
    business_environment,
    initialize_dependencies,
)
from dependency_install import DependencyInstallError


class StartupError(RuntimeError):
    pass


def initialize_runtime(seed: Path, runtime: Path) -> None:
    """Copy the image once; an incomplete existing directory is never replaced."""
    marker = runtime / ".initialized"
    initializing = not runtime.exists()
    if runtime.is_symlink():
        raise StartupError("runtime must not be a link / 程序目录不能是链接")
    if runtime.exists():
        if not runtime.is_dir() or not marker.is_file() or marker.is_symlink():
            raise StartupError(
                "runtime initialization is incomplete; inspect and repair manually / "
                "程序目录初始化未完成，请检查并人工修复"
            )
    else:
        # Create the destination before copying. Failure leaves no success marker;
        # subsequent starts refuse it instead of overwriting possible user changes.
        shutil.copytree(seed, runtime, symlinks=True)
    required = (
        "scripts/start-unified-app.sh",
        "scripts/unified-http-gateway.mjs",
        "apps/web/server.js",
        "apps/api-python/app/bootstrap/prestart.py",
    )
    if any(not (runtime / name).is_file() for name in required):
        raise StartupError("runtime files are missing / 程序文件缺失")
    # Probe with actual writes under the configured UID, without chmod/chown.
    for directory in (runtime, runtime / "apps/web/.next/cache"):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    if initializing:
        marker.write_text("1\n", encoding="utf-8")


def run_application(runtime: Path, storage: Path) -> int:
    stop_signal = 0

    def stop(signum: int, _frame: object) -> None:
        nonlocal stop_signal
        stop_signal = stop_signal or signum

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            raise StartupError("cannot enable child reaping / 无法启用子进程回收")

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
    stage_file = storage / "update-tmp/startup-stage"
    ready_file = storage / "update-tmp/worker-ready"

    def launch() -> subprocess.Popen:
        stage_file.unlink(missing_ok=True)
        ready_file.unlink(missing_ok=True)
        return subprocess.Popen(
            ["sh", str(runtime / "scripts/start-unified-app.sh")],
            cwd=runtime,
            env={
                **environment,
                "IMPORT_WORKER_READY_FILE": str(ready_file),
                "SHUKU_STARTUP_STATUS_FILE": str(stage_file),
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
                    fail("PREFLIGHT_FAILED")
                else:
                    try:
                        installer.verify_dependencies()
                    except Exception as error:  # noqa: BLE001 - owned preflight boundary
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
                        raise InstallError("STOP_FAILED")
                    installer.backup()
                    if stop_signal:
                        raise InstallError("CONTAINER_STOPPED")
                    installer.synchronize()
                    if stop_signal:
                        raise InstallError("CONTAINER_STOPPED")
                    installer.phase("starting")
                    child = launch()
                    deadline = time.monotonic() + 180
                except Exception as error:  # noqa: BLE001 - owned installation boundary
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
        elif installing and installer.state["phase"] == "starting":
            if child.returncode is not None:
                phase = stage_file.read_text().strip() if stage_file.exists() else ""
                fail("MIGRATION_FAILED" if phase == "migration" else "STARTUP_FAILED")
            elif time.monotonic() >= deadline:
                core_ready = core_application_ready(
                    installer.state["target"]["version"]
                )
                fail("WORKER_STARTUP_FAILED" if core_ready else "STARTUP_TIMEOUT")
                if not core_ready:
                    os.kill(child.pid, signal.SIGTERM)
            elif application_ready(
                child.pid, installer.state["target"]["version"], ready_file
            ):
                try:
                    installer.success()
                except (OSError, ValueError, DependencyInstallError, InstallError):
                    fail("RESULT_WRITE_FAILED")
                    os.kill(child.pid, signal.SIGTERM)
                else:
                    installer = Installation(storage)
                    installer.cancelled = lambda: bool(stop_signal)
                    installing = False
                    stopped = False
        elif (  # noqa: SIM102
            not stop_signal
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
                except Exception as error:
                    if installer.state is not None:
                        fail(
                            str(error)
                            if isinstance(error, (InstallError, DependencyInstallError))
                            else "PREFLIGHT_FAILED"
                        )
                    else:
                        installer.close()
                        raise StartupError(
                            "invalid install request / 安装请求无效"
                        ) from error
        if child.returncode is not None and not installing:
            if empty:
                break
            # Ordinary termination retains the established orphan cleanup. An
            # installation failure must not kill remaining tools and then copy.
            if installer.state is None or stop_signal:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(0.2)
    return (
        128 + stop_signal
        if stop_signal
        else (child.returncode or (1 if stopped else 0))
    )


def application_ready(group: int, version: str, ready_file: Path) -> bool:
    try:
        identity = json.loads(ready_file.read_text())
        worker_pid = int(identity["pid"])
        fields = Path(f"/proc/{worker_pid}/stat").read_text().rsplit(")", 1)[1].split()
        if (
            fields[0] == "Z"
            or int(fields[1]) != group
            or fields[19] != identity["startTime"]
        ):
            return False
        if os.getpgid(worker_pid) != worker_pid:
            return False
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False
    return core_application_ready(version)


def core_application_ready(version: str) -> bool:
    """Core acceptance does not depend on optional queue recovery/maintenance."""
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/openapi.json", timeout=1
        ) as response:
            if json.load(response)["info"]["version"] != version:
                return False
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/health", timeout=1
        ) as response:
            if response.status != 200:
                return False
        port = int(os.environ.get("NEXT_INTERNAL_PORT", "3001"))
        base_path = (
            os.environ.get("NEXT_PUBLIC_BASE_PATH")
            or os.environ.get("SHUKU_BASE_PATH")
            or os.environ.get("COOKIE_PATH", "").rstrip("/")
            or ""
        )
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{base_path}/", timeout=1
        ) as response:
            if response.status != 200:
                return False
        gateway_port = int(os.environ.get("PORT", "3000"))
        with urllib.request.urlopen(
            f"http://127.0.0.1:{gateway_port}{base_path}/api/health", timeout=1
        ) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError):
        return False


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
    backup_database(
        storage, storage / "update-tmp/database-before-dependency-conversion.sqlite3"
    )
    initialize_dependencies(storage, dependency_seed)
    # Use the existing schema barrier. Unknown/newer schemas are never stamped or downgraded.
    subprocess.run(
        [
            str(storage / "dependencies/python/bin/python"),
            "-c",
            "from app.bootstrap.prestart import verify_current_schema; from app.db.session import engine; verify_current_schema(engine)",
        ],
        cwd=runtime / "apps/api-python",
        env=business_environment(storage),
        check=True,
        capture_output=True,
    )
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
                raise StartupError(
                    "application is already running / 应用已在运行"
                ) from None
            if any(
                path.exists() or path.is_symlink()
                for path in (
                    state / "installation-incomplete",
                    state / "install-request.json",
                )
            ):
                raise StartupError(
                    "installation unfinished; inspect update-tmp/installation.log and repair manually / 安装未完成，请检查更新日志并人工修复，禁止自动重试"
                )
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
            if runtime.exists():
                identity = json.loads((runtime / "application.json").read_text())
                if identity.get("protocol") != 2:
                    raise StartupError(
                        "legacy runtime requires --convert-legacy while stopped / 旧程序须停机后显式转换"
                    )
                if not (storage / "dependencies/installed.json").is_file():
                    raise StartupError(
                        "missing business environment / 缺少业务依赖环境"
                    )
            initialize_runtime(seed, runtime)
            fixed_environment = Path(__file__).with_name("environment.json")
            if fixed_environment.is_file():
                fixed = json.loads(fixed_environment.read_text())["environment"]
                identity = json.loads((runtime / "application.json").read_text())
                if identity.get("protocol") != 2 or identity["environment"] != fixed:
                    raise StartupError("incompatible base environment / 基础环境不兼容")
            initialize_dependencies(storage, dependency_seed)
            print("runtime ready / 持久化程序目录就绪", flush=True)
            return run_application(runtime, storage)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        shutil.Error,
        StartupError,
        DependencyError,
        InstallError,
        KeyError,
    ) as error:
        # Do not expose private paths or dump a traceback into container logs.
        detail = (
            str(error)
            if isinstance(error, (StartupError, DependencyError))
            else type(error).__name__
        )
        print(
            f"container startup failed ({detail}); check storage permissions and runtime integrity; "
            "no application started / 容器启动失败，请检查存储权限和程序目录完整性，未启动应用",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
