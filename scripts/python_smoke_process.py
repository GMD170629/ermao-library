"""Bounded process and file-log handling for the Python release smokes.

The release checks intentionally launch the already-selected Python interpreter
directly.  Keeping stdout out of a pipe means cleanup cannot block forever on a
child that kept writing after its parent was signalled.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class LoggedProcess:
    """A smoke child with bounded, process-group-aware shutdown."""

    process: subprocess.Popen[str]
    log_path: Path
    _log_file: TextIO
    _log_closed: bool = False

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def _close_log(self) -> None:
        if self._log_closed:
            return
        self._log_file.flush()
        self._log_file.close()
        self._log_closed = True

    def read_log(self) -> str:
        self._close_log()
        try:
            return self.log_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def stop(self, *, timeout: float = 8.0) -> str:
        """Stop this child and return its complete file-backed output.

        The normal signal is given to the process group.  A bounded wait is
        followed by an exact-PID tree kill on Windows or a process-group kill
        on POSIX.  Only this helper's process PID is ever targeted.
        """

        if self.poll() is None:
            _request_stop(self.process)
            _wait_for_exit(self.process, timeout)
        if self.poll() is None:
            _force_stop(self.process)
            _wait_for_exit(self.process, timeout)
        if self.poll() is None:
            self._close_log()
            raise TimeoutError(
                f"smoke process {self.process.pid} did not stop within {timeout}s"
            )
        return self.read_log()


def start_logged_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log_path: Path,
) -> LoggedProcess:
    """Start one smoke child with no PIPE-backed output channel."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8", buffering=1)
    child_env = dict(env)
    child_env["PYTHONIOENCODING"] = "utf-8"
    try:
        if os.name == "nt":
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                env=child_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                env=child_env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
    except BaseException:
        log_file.close()
        raise
    return LoggedProcess(process=process, log_path=log_path, _log_file=log_file)


def _wait_for_exit(process: subprocess.Popen[str], timeout: float) -> None:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return


def _request_stop(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            return
        except ProcessLookupError:
            return
        except ValueError:
            process.terminate()
            return
    try:
        # POSIX start_new_session makes this PID the process-group leader.
        os.kill(-process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _force_stop(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "taskkill.exe",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                return
            return
        if result.returncode == 0:
            return
        try:
            process.kill()
        except ProcessLookupError:
            return
        return
    try:
        # SIGKILL is POSIX-only; the fallback is unreachable on Windows but
        # keeps the cross-platform type boundary explicit for the stub set.
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        os.kill(-process.pid, kill_signal)
    except ProcessLookupError:
        return


__all__ = ["LoggedProcess", "start_logged_process"]
