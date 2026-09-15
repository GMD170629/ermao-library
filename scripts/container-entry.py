#!/usr/bin/env python3
"""Fixed container entry. Standard library only; never import runtime code."""

from __future__ import annotations

import ctypes
import fcntl
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


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
    # Adopt and reap orphaned grandchildren even when this entry is not PID 1.
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise StartupError("cannot enable child reaping / 无法启用子进程回收")

    environment = {
        **os.environ,
        "STORAGE_ROOT": str(storage),
        "ROOT_DIR": str(runtime),
        "PYTHON_API_DIR": str(runtime / "apps/api-python"),
        "NEXT_SERVER": str(runtime / "apps/web/server.js"),
        "GATEWAY_SERVER": str(runtime / "scripts/unified-http-gateway.mjs"),
    }
    child = subprocess.Popen(
        ["sh", str(runtime / "scripts/start-unified-app.sh")],
        cwd=runtime,
        env=environment,
        start_new_session=True,
    )
    forwarded = False
    # waitpid is the sole reaper, including for the Popen child. Popen.poll(),
    # wait() and send_signal() would compete for its status (send_signal polls).
    while child.returncode is None:
        if stop_signal and not forwarded:
            # The existing script owns graceful shutdown of API and Worker.
            os.kill(child.pid, stop_signal)
            forwarded = True
        pid, status = os.waitpid(-1, os.WNOHANG)
        if pid == child.pid:
            child.returncode = os.waitstatus_to_exitcode(status)
        elif pid == 0:
            time.sleep(0.2)
    # The shell has waited for its services. Terminate any orphaned tools left
    # by those services, then reap them. Never restart on ordinary termination.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            break
    return 128 + stop_signal if stop_signal else (child.returncode or 0)


def main() -> int:
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
            initialize_runtime(seed, runtime)
            print("runtime ready / 持久化程序目录就绪", flush=True)
            return run_application(runtime, storage)
    except (OSError, shutil.Error, StartupError) as error:
        # Do not expose private paths or dump a traceback into container logs.
        detail = str(error) if isinstance(error, StartupError) else type(error).__name__
        print(
            f"container startup failed ({detail}); check storage permissions and runtime integrity; "
            "no application started / 容器启动失败，请检查存储权限和程序目录完整性，未启动应用",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
