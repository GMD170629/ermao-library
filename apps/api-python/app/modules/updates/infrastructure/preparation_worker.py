"""One owned preparation thread, a file lock and the most recent durable result."""

from __future__ import annotations

import errno
import gzip
import hashlib
import logging
import os
import shutil
import tarfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from ..application.models import Package, PreparationState, UpdateError
from .archive import check_space, extract_package
from .official_source import ByteSource, package_url

LOGGER = logging.getLogger(__name__)

ACTIVE = {"downloading", "verifying", "extracting"}


class PreparationWorker:
    def __init__(self, storage: Path, transport: ByteSource) -> None:
        self.storage = storage
        self.root = storage / "update-tmp"
        self.transport = transport
        self.thread: threading.Thread | None = None
        self.cancelled = threading.Event()
        self.guard = threading.Lock()

    def _lock(self) -> IO[str]:
        try:
            if os.name != "posix":
                raise UpdateError("UNSUPPORTED_DEPLOYMENT")
            if self.root.is_symlink():
                raise UpdateError("UNSAFE_STORAGE")
            self.root.mkdir(parents=True, exist_ok=True)
            return os.fdopen(
                os.open(
                    self.root / "prepare.lock",
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                    0o600,
                ),
                "w",
            )
        except OSError as error:
            raise UpdateError("STORAGE_UNAVAILABLE") from error

    def _read(self) -> PreparationState:
        try:
            path = self.root / "preparation.json"
            if path.is_symlink():
                raise UpdateError("UNSAFE_STORAGE")
            if not path.exists():
                return PreparationState()
            if path.stat().st_size > 16 * 1024:
                raise UpdateError("INVALID_STATE")
            return PreparationState.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as error:
            raise UpdateError("INVALID_STATE") from error

    def _write(self, state: PreparationState) -> PreparationState:
        try:
            state = state.model_copy(
                update={"updated_at": datetime.now(UTC).isoformat()}
            )
            temporary = self.root / "preparation.json.tmp"
            with os.fdopen(
                os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                    0o600,
                ),
                "w",
            ) as stream:
                stream.write(state.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.root / "preparation.json")
            return state
        except OSError as error:
            raise UpdateError("STATE_WRITE_FAILED") from error

    def status(self) -> PreparationState:
        import fcntl

        if os.name != "posix":
            raise UpdateError("UNSUPPORTED_DEPLOYMENT")
        with self.guard, self._lock() as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self._read()
            state = self._read()
            if state.phase in ACTIVE:
                state = self._write(
                    state.model_copy(
                        update={
                            "phase": "failed",
                            "failed_phase": state.phase,
                            "error": "PREPARATION_INTERRUPTED",
                        }
                    )
                )
            return state

    def submit(self, package: Package) -> PreparationState:
        import fcntl

        if os.name != "posix":
            raise UpdateError("UNSUPPORTED_DEPLOYMENT")
        with self.guard:
            if self.cancelled.is_set():
                raise UpdateError("PREPARATION_CANCELLED")
            lock = self._lock()
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise UpdateError("UPDATE_BUSY") from None
                previous = self._read()
                if previous.phase == "ready" and previous.target == package:
                    lock.close()
                    return previous
                state = self._write(
                    PreparationState(
                        phase="downloading",
                        target=package,
                        started_at=datetime.now(UTC).isoformat(),
                    )
                )
                self.thread = threading.Thread(
                    target=self._run,
                    args=(package, state, lock),
                    name="application-update-preparation",
                    daemon=False,
                )
                self.thread.start()
                return state
            except Exception:
                lock.close()
                raise

    def _run(self, package: Package, state: PreparationState, lock: IO[str]) -> None:
        work = self.root / "prepared"
        try:
            if work.is_symlink() or (self.storage / "runtime").is_symlink():
                raise UpdateError("UNSAFE_STORAGE")
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(mode=0o700)
            if not os.access(self.storage / "runtime", os.W_OK | os.X_OK):
                raise UpdateError("RUNTIME_NOT_WRITABLE")
            check_space(work, package.size + 2 * package.expanded_size)
            archive = work / "application.tar.gz"
            digest = hashlib.sha256()
            downloaded = 0
            reported = 0
            with archive.open("xb") as output:
                for chunk in self.transport.chunks(
                    package_url(package), package.size, 600
                ):
                    if self.cancelled.is_set():
                        raise UpdateError("PREPARATION_CANCELLED")
                    downloaded += len(chunk)
                    if downloaded > package.size:
                        raise UpdateError("SIZE_LIMIT")
                    output.write(chunk)
                    digest.update(chunk)
                    if downloaded - reported >= 1024 * 1024:
                        state = self._write(
                            state.model_copy(update={"downloaded": downloaded})
                        )
                        reported = downloaded
            state = self._write(
                state.model_copy(
                    update={"phase": "verifying", "downloaded": downloaded}
                )
            )
            if downloaded != package.size or digest.hexdigest() != package.sha256:
                raise UpdateError("DIGEST_MISMATCH")
            state = self._write(state.model_copy(update={"phase": "extracting"}))
            extract_package(archive, work / "app", package, self.cancelled)
            check_space(work, package.expanded_size)
            if self.cancelled.is_set():
                raise UpdateError("PREPARATION_CANCELLED")
            self._write(state.model_copy(update={"phase": "ready"}))
        except Exception as error:  # noqa: BLE001 - owned background task boundary
            # This is the owned task boundary. Do not persist private URLs/paths.
            if isinstance(error, UpdateError):
                code = error.code
            elif isinstance(error, (tarfile.TarError, gzip.BadGzipFile, EOFError)):
                code = "INVALID_ARCHIVE"
            elif isinstance(error, PermissionError):
                code = "STORAGE_NOT_WRITABLE"
            elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
                code = "INSUFFICIENT_SPACE"
            else:
                code = "PREPARATION_FAILED"
            LOGGER.error("application_update phase=%s reason=%s", state.phase, code)
            try:
                self._write(
                    state.model_copy(
                        update={
                            "phase": "failed",
                            "failed_phase": state.phase,
                            "error": code,
                        }
                    )
                )
            except UpdateError as persistence_error:
                LOGGER.error(
                    "application_update phase=%s reason=%s",
                    state.phase,
                    persistence_error.code,
                )
        finally:
            lock.close()

    def close(self) -> None:
        with self.guard:
            self.cancelled.set()
            thread = self.thread
        if thread is not None:
            thread.join()
