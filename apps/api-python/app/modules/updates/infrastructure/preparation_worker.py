"""One owned preparation thread, a file lock and the most recent durable result."""

from __future__ import annotations

import errno
import gzip
import hashlib
import json
import logging
import os
import shutil
import tarfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from shuku_dependencies import canonical_digest

from ..application.dependency_release import (
    MAX_TOTAL,
    CodePackage,
    ReleaseManifest,
    difference,
    package_key,
)
from ..application.models import (
    MAX_PACKAGE,
    Environment,
    GHCRReleaseReference,
    Package,
    PreparationState,
    PreparationSummary,
    ReleaseReference,
    UpdateError,
)
from .archive import extract_package
from .dependency_preparation import (
    read_bounded,
    read_local,
    verify_dependency_artifact,
)
from .ghcr_source import blob_url
from .official_source import ByteSource, artifact_url, package_url

LOGGER = logging.getLogger(__name__)

ACTIVE = {"downloading", "verifying", "extracting"}


class PreparationWorker:
    def __init__(
        self,
        storage: Path,
        transport: ByteSource,
        environment: Environment | None = None,
    ) -> None:
        self.environment = environment
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

    def submit(self, package: Package | ReleaseReference) -> PreparationState:
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
                if (self.root / "install-request.json").exists() or (
                    self.root / "installation-incomplete"
                ).exists():
                    raise UpdateError("UPDATE_BUSY")
                previous = self._read()
                if (
                    previous.phase == "ready"
                    and previous.target == package
                    and isinstance(package, Package)
                ):
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

    def install(
        self,
        version: str,
        sha256: str,
        environment: Environment,
        current: str,
        plan_sha256: str | None = None,
    ) -> PreparationState:
        import fcntl
        import json

        with self.guard, self._lock() as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UpdateError("UPDATE_BUSY") from None
            request = self.root / "install-request.json"
            if (
                request.exists()
                or request.is_symlink()
                or (self.root / "installation-incomplete").exists()
            ):
                raise UpdateError("UPDATE_BUSY")
            state = self._read()
            if (
                state.phase != "ready"
                or state.target is None
                or state.target.version != version
                or state.target.sha256 != sha256
            ):
                raise UpdateError("PACKAGE_NOT_READY")
            if isinstance(state.target, ReleaseReference):
                from .install_plan import validate_prepared

                try:
                    validate_prepared(self.storage, state, environment, plan_sha256)
                except UpdateError:
                    raise
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise UpdateError("INVALID_PREPARED_PLAN") from error
            # Durable reservation under prepare.lock. The fixed entry claims this
            # same lock; preparation checks the reservation before deleting files.
            with request.open("x") as stream:
                json.dump(
                    {
                        "target": state.target.model_dump(),
                        "current": current,
                        "plan_sha256": plan_sha256,
                    },
                    stream,
                )
                stream.flush()
                os.fsync(stream.fileno())
            return self._write(state.model_copy(update={"phase": "requested"}))

    def _run(
        self,
        package: Package | ReleaseReference,
        state: PreparationState,
        lock: IO[str],
    ) -> None:
        work = self.root / "prepared"
        try:
            if work.is_symlink() or (self.storage / "runtime").is_symlink():
                raise UpdateError("UNSAFE_STORAGE")
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(mode=0o700)
            if isinstance(package, ReleaseReference):
                self._prepare_v2(package, state, work)
                return
            if not os.access(self.storage / "runtime", os.W_OK | os.X_OK):
                raise UpdateError("RUNTIME_NOT_WRITABLE")
            archive = work / "application.tar.gz"
            state = self._download(
                package_url(package), archive, package.size, package.sha256, state
            )
            state = self._write(state.model_copy(update={"phase": "verifying"}))
            state = self._write(state.model_copy(update={"phase": "extracting"}))
            extract_package(
                archive, work / "app", package, self.cancelled, verify_identity=False
            )
            if self.cancelled.is_set():
                raise UpdateError("PREPARATION_CANCELLED")
            self._write(state.model_copy(update={"phase": "ready"}))
        except Exception as error:  # noqa: BLE001 - owned background task boundary
            state = self._read()
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

    def _download(
        self, url: str, path: Path, size: int, sha256: str, state: PreparationState
    ) -> PreparationState:
        digest = hashlib.sha256()
        received = reported = 0
        with path.open("xb") as output:
            for chunk in self.transport.chunks(url, MAX_PACKAGE, 600):
                if self.cancelled.is_set():
                    raise UpdateError("PREPARATION_CANCELLED")
                received += len(chunk)
                if received > MAX_PACKAGE or state.downloaded + received > MAX_TOTAL:
                    raise UpdateError("SIZE_LIMIT")
                output.write(chunk)
                digest.update(chunk)
                if received - reported >= 1024 * 1024:
                    self._write(
                        state.model_copy(
                            update={"downloaded": state.downloaded + received}
                        )
                    )
                    reported = received
        state = self._write(
            state.model_copy(update={"downloaded": state.downloaded + received})
        )
        if digest.hexdigest() != sha256:
            raise UpdateError("DIGEST_MISMATCH")
        return state

    @staticmethod
    def _artifact_url(reference: ReleaseReference, filename: str, digest: str) -> str:
        if isinstance(reference, GHCRReleaseReference):
            return blob_url(digest)
        return artifact_url(reference.version, filename)

    def _prepare_v2(
        self, reference: ReleaseReference, state: PreparationState, work: Path
    ) -> None:
        manifest_path = work / "release.json"
        state = self._download(
            package_url(reference),
            manifest_path,
            reference.size,
            reference.sha256,
            state,
        )
        try:
            manifest = ReleaseManifest.model_validate_json(
                read_bounded(manifest_path, 32 * 1024 * 1024), context={"runtime": True}
            )
        except ValueError as error:
            raise UpdateError("INVALID_MANIFEST") from error
        local, baseline = read_local(self.storage)
        plan = difference(local, manifest.dependencies)
        selected = [
            p for p in manifest.dependencies.packages if package_key(p) in plan.install
        ]
        dependency_bytes = sum(p.artifact.size for p in selected)
        total = reference.size + manifest.code.size + dependency_bytes
        summary = PreparationSummary(
            dependency_identity=manifest.dependencies.identity,
            baseline=baseline,
            code_sha256=manifest.code.sha256,
            keep=len(plan.keep),
            install=len(plan.install),
            remove=len(plan.remove),
            total_bytes=total,
            dependency_bytes=dependency_bytes,
        )
        state = self._write(state.model_copy(update={"summary": summary}))
        code = manifest.code
        state = self._download(
            self._artifact_url(reference, code.filename, code.sha256),
            work / code.filename,
            code.size,
            code.sha256,
            state,
        )
        state = self._write(state.model_copy(update={"phase": "extracting"}))
        extract_package(
            work / code.filename,
            work / "app",
            CodePackage.model_validate(
                dict(
                    version=manifest.version,
                    environment=manifest.environment,
                    **code.model_dump(),
                ),
                context={"runtime": True},
            ),
            self.cancelled,
            verify_identity=False,
        )
        verified = [code.model_dump()]
        expanded = 0
        for package in selected:
            item = package.artifact
            state = self._write(state.model_copy(update={"phase": "downloading"}))
            state = self._download(
                self._artifact_url(reference, item.filename, item.sha256),
                work / item.filename,
                item.size,
                item.sha256,
                state,
            )
            state = self._write(state.model_copy(update={"phase": "verifying"}))
            expanded += verify_dependency_artifact(
                work / item.filename,
                package,
                manifest.dependencies,
                self.cancelled,
                verify_identity=False,
            )
            if expanded > MAX_TOTAL:
                raise UpdateError("SIZE_LIMIT")
            verified.append(
                {"filename": item.filename, "size": item.size, "sha256": item.sha256}
            )
        if self.cancelled.is_set():
            raise UpdateError("PREPARATION_CANCELLED")
        with (work / "plan.json").open("x") as output:
            json.dump(
                {
                    "protocol": 2,
                    "version": reference.version,
                    "manifest_sha256": reference.sha256,
                    "baseline": baseline,
                    "dependency_identity": manifest.dependencies.identity,
                    "difference": plan.model_dump(),
                    "verified": verified,
                    "downloaded": state.downloaded,
                },
                output,
            )
            output.flush()
            os.fsync(output.fileno())
        self._write(
            state.model_copy(
                update={
                    "phase": "ready",
                    "summary": summary.model_copy(
                        update={
                            "verified_artifacts": len(verified),
                            "plan_sha256": canonical_digest(
                                json.loads((work / "plan.json").read_bytes())
                            ),
                        }
                    ),
                }
            )
        )

    def close(self) -> None:
        with self.guard:
            self.cancelled.set()
            thread = self.thread
        if thread is not None:
            thread.join()
