"""Start the opt-in release live fixture used by the real Chrome E2E.

This launcher owns only process isolation and legal checked-in sample files.
The browser test owns setup, authentication, library creation, scanning and
all assertions.  No database rows are created here and no production path is
read or written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
WEB_ROOT = REPO_ROOT / "apps" / "web"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(API_ROOT))

from app.modules.publications.infrastructure.chapter_core import ChapterCore
from python_backend_sample_smoke import (
    free_port,
    sha256_file,
    wait_for_health,
    wait_for_worker,
    write_comic_fixture,
    write_epub_fixture,
    write_pdf_fixture,
)
from python_smoke_process import LoggedProcess, start_logged_process

FORBIDDEN_PORTS = {3000, 3100, 8000}
DEFAULT_WEB_PORT = 3101
DEFAULT_STARTUP_TIMEOUT_SECONDS = 1_200
PROCESS_STOP_TIMEOUT_SECONDS = 12
APPLICATION_SOURCE_ROOTS = (
    "apps/api-python/app",
    *(
        f"apps/web/{directory}"
        for directory in (
            "app",
            "components",
            "features",
            "generated",
            "i18n",
            "lib",
            "shared",
            "styles",
            "types",
        )
    ),
    "packages/reader-core/src",
)
APPLICATION_SOURCE_FILES = (
    "apps/web/next.config.ts",
    "apps/web/public/sw.js",
    "packages/reader-contracts/reader-http-error-statuses.json",
    "packages/reader-contracts/reader-navigation-policy.json",
    "packages/reader-contracts/reader-progress-timing.json",
    "packages/reader-contracts/reader-safety-policy.json",
    "packages/reader-contracts/reader-settings.json",
)
DEFAULT_AUDIO_CORPUS_ROOT = (
    REPO_ROOT
    / "artifacts"
    / "releases"
    / "1.0"
    / "197e81a808ba32595a8a6ffeda62422b3a7d3473"
    / "corpus-format-library-20260906"
)
AUDIO_CORPUS_FILES = (
    ("MP3", "公开格式测试 - AUDIO - MP3.mp3", "release-alice-mp3.mp3", "audio/mpeg"),
    ("AAC", "公开格式测试 - AUDIO - AAC.aac", "release-alice-aac.aac", "audio/aac"),
    ("WAV", "公开格式测试 - AUDIO - WAV.wav", "release-alice-wav.wav", "audio/wav"),
    (
        "FLAC",
        "公开格式测试 - AUDIO - FLAC.flac",
        "release-alice-flac.flac",
        "audio/flac",
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--shutdown-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--lifetime-seconds", type=int, default=600)
    parser.add_argument(
        "--startup-timeout-seconds", type=int, default=DEFAULT_STARTUP_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--web-runtime", choices=("development", "production"), default="development"
    )
    parser.add_argument(
        "--web-hostname",
        choices=("127.0.0.1", "localhost", "release-live.localhost"),
        default="127.0.0.1",
    )
    return parser.parse_args()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _event(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(message.rstrip() + "\n")


class FixtureStoppedError(RuntimeError):
    """The browser cancelled startup before the next fixture operation."""


class NextConfigurationConflict(RuntimeError):
    """A configuration file no longer contains this run's installed bytes."""


@contextmanager
def _configuration_file(path: Path) -> Iterator[BinaryIO]:
    """Hold the file while comparing and replacing its run-owned contents.

    Windows denies other write/delete handles during this short operation.
    POSIX uses the same exclusive advisory locking convention as flock writers.
    No lock is held while Next or the browser runs.
    """
    if path.is_symlink():
        raise NextConfigurationConflict(f"Refusing symlink configuration: {path.name}")
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(str(path), 0xC0000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            close_handle = kernel.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle(handle)
            raise
        with os.fdopen(descriptor, "r+b") as stream:
            yield stream
    else:
        import fcntl

        with path.open("r+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


@dataclass
class NextConfigurationFile:
    path: Path
    original: bytes
    installed: bytes
    changed: bool = False

    def install(self) -> None:
        with _configuration_file(self.path) as stream:
            if stream.read() != self.original:
                raise NextConfigurationConflict(
                    f"Configuration changed before fixture setup: {self.path.name}"
                )
            self.changed = True
            self._write(stream, self.installed)

    def restore(self) -> None:
        if not self.changed:
            return
        with _configuration_file(self.path) as stream:
            current = stream.read()
            if current == self.original:
                self.changed = False
                return
            if current != self.installed:
                raise NextConfigurationConflict(
                    f"Concurrent or unexpected Next configuration change; preserved "
                    f"{self.path.name}. Original bytes are in next-config-before."
                )
            self._write(stream, self.original)
            self.changed = False

    @staticmethod
    def _write(stream: BinaryIO, content: bytes) -> None:
        stream.seek(0)
        stream.write(content)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


@dataclass
class FixtureLifecycle:
    artifact_dir: Path
    stop_file: Path
    shutdown_file: Path
    startup_deadline: float
    stage: str = "preflight"
    processes: dict[str, LoggedProcess] = field(default_factory=dict)
    configuration: list[NextConfigurationFile] = field(default_factory=list)
    next_dist_path: Path | None = None

    @property
    def event_log(self) -> Path:
        return self.artifact_dir / "fixture.log"

    def check_startup(self) -> None:
        if self.stop_file.is_file():
            raise FixtureStoppedError(f"Fixture startup cancelled during {self.stage}")
        if time.monotonic() >= self.startup_deadline:
            raise TimeoutError(f"Fixture startup deadline exceeded during {self.stage}")


@contextmanager
def _fixture_lifecycle(lifecycle: FixtureLifecycle) -> Iterator[None]:
    primary_error: BaseException | None = None
    cleanup_errors: list[Exception] = []
    try:
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        # This is the fixture process boundary: contain each cleanup failure so
        # all owned children are attempted and the original error survives.
        for label, process in reversed(tuple(lifecycle.processes.items())):
            try:
                _stop_process(label, process, lifecycle.event_log)
            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                cleanup_errors.append(error)
        processes_stopped = not cleanup_errors
        if processes_stopped:
            for configuration in reversed(lifecycle.configuration):
                try:
                    configuration.restore()
                except (OSError, RuntimeError, ValueError) as error:
                    cleanup_errors.append(error)
            if not cleanup_errors and lifecycle.next_dist_path is not None:
                try:
                    # Only a path validated and claimed by this run is assigned.
                    if lifecycle.next_dist_path.exists():
                        resolved_dist = lifecycle.next_dist_path.resolve()
                        if (
                            resolved_dist != lifecycle.next_dist_path
                            or resolved_dist.parent != WEB_ROOT.resolve()
                        ):
                            raise ValueError("Next cleanup escaped the Web workspace")
                        shutil.rmtree(resolved_dist)
                except (OSError, ValueError) as error:
                    cleanup_errors.append(error)
        try:
            if primary_error is not None:
                _event(
                    lifecycle.event_log,
                    "".join(traceback.format_exception(primary_error)),
                )
            for error in cleanup_errors:
                _event(
                    lifecycle.event_log,
                    f"cleanup_error={type(error).__name__}: {error}",
                )
            if not cleanup_errors:
                lifecycle.shutdown_file.write_text("stopped\n", encoding="utf-8")
            _write_json(
                lifecycle.artifact_dir / "shutdown-result.json",
                {
                    "status": "cleanup_failed" if cleanup_errors else "stopped",
                    "stage": lifecycle.stage,
                    "primaryError": str(primary_error)
                    if primary_error is not None
                    else None,
                    "cleanupErrors": [
                        f"{type(error).__name__}: {error}" for error in cleanup_errors
                    ],
                    "processesStopped": processes_stopped,
                },
            )
        except (OSError, ValueError) as error:
            cleanup_errors.append(error)
        if primary_error is not None and cleanup_errors:
            raise BaseExceptionGroup(
                "Fixture failed and cleanup also failed",
                [primary_error, *cleanup_errors],
            ) from None
        if cleanup_errors:
            raise ExceptionGroup("Fixture cleanup failed", cleanup_errors)


def _prepare_next_configuration(
    lifecycle: FixtureLifecycle, dist_name: str, runtime: str
) -> None:
    """Install only the run's type paths; restore exact prior bytes by comparison."""
    lifecycle.stage = "next-configuration"
    lifecycle.check_startup()
    tsconfig_path = WEB_ROOT / "tsconfig.json"
    declarations_path = WEB_ROOT / "next-env.d.ts"
    original_config = tsconfig_path.read_bytes()
    config: object = json.loads(original_config)
    if not isinstance(config, dict):
        raise TypeError("Next fixture requires an object tsconfig")
    includes = config.get("include")
    options = config.get("compilerOptions")
    if (
        not isinstance(includes, list)
        or not all(isinstance(value, str) for value in includes)
        or not isinstance(options, dict)
    ):
        raise ValueError("Next fixture requires explicit include and compilerOptions")
    for suffix in ("types/**/*.ts", "dev/types/**/*.ts"):
        include = f"{dist_name}/{suffix}"
        if include not in includes:
            includes.append(include)
    options["tsBuildInfoFile"] = f"{dist_name}/cache/tsconfig.tsbuildinfo"
    installed_config = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    original_declarations = declarations_path.read_bytes()
    types_dir = f"{dist_name}/dev" if runtime == "development" else dist_name
    installed_declarations, count = re.subn(
        rb'(?m)^import ["\']\./[^"\'\r\n]+/types/routes\.d\.ts["\'];',
        f'import "./{types_dir}/types/routes.d.ts";'.encode(),
        original_declarations,
    )
    if count != 1:
        raise ValueError(
            "Next fixture requires one existing generated route-type import"
        )
    changes = [
        NextConfigurationFile(tsconfig_path, original_config, installed_config),
        NextConfigurationFile(
            declarations_path, original_declarations, installed_declarations
        ),
    ]
    backup_dir = lifecycle.artifact_dir / "next-config-before"
    backup_dir.mkdir()
    for change in changes:
        (backup_dir / change.path.name).write_bytes(change.original)
    lifecycle.configuration.extend(changes)
    for change in changes:
        change.install()


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _resolve_port(value: int, name: str) -> int:
    port = free_port() if value == 0 else value
    if port in FORBIDDEN_PORTS:
        raise RuntimeError(
            f"{name}={port} is reserved for an existing service; choose an isolated port"
        )
    if not 1024 <= port <= 65535:
        raise RuntimeError(f"{name} must be between 1024 and 65535: {port}")
    if not _port_is_available(port):
        raise RuntimeError(f"{name}={port} is already in use")
    return port


def _resolve_ffprobe() -> str | None:
    configured = os.environ.get("FFPROBE_PATH")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    return shutil.which("ffprobe")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "unknown"


def _source_metadata(path: Path, fixture_path: Path) -> dict[str, object]:
    return {
        "sourcePath": str(path),
        "fixturePath": str(fixture_path),
        "sourceSha256": sha256_file(path),
        "fixtureSha256": sha256_file(fixture_path),
        "sizeBytes": fixture_path.stat().st_size,
    }


def _build_audio_samples(
    library_root: Path,
    corpus_root: Path,
) -> list[dict[str, object]]:
    manifest_path = corpus_root / "公开格式测试 - 来源与校验.md"
    if not corpus_root.is_dir() or not manifest_path.is_file():
        raise RuntimeError(f"audio corpus manifest is missing: {manifest_path}")
    samples: list[dict[str, object]] = []
    for label, source_name, fixture_name, expected_mime in AUDIO_CORPUS_FILES:
        source_path = corpus_root / source_name
        fixture_path = library_root / fixture_name
        if not source_path.is_file():
            raise RuntimeError(f"audio corpus sample is missing: {source_path}")
        shutil.copy2(source_path, fixture_path)
        samples.append(
            {
                "format": f"AUDIO_{label}",
                "kind": "audio",
                "sourceExtension": source_path.suffix.lower(),
                "expectedMime": expected_mime,
                "corpusManifest": str(manifest_path),
                "durationClaim": "format fixture; duration must be verified by the actual engine",
                **_source_metadata(source_path, fixture_path),
            }
        )
    return samples


def _build_samples(library_root: Path, corpus_root: Path) -> list[dict[str, object]]:
    library_root.mkdir(parents=True, exist_ok=True)
    epub = library_root / "release-reader-v2.epub"
    pdf = library_root / "release-reading-notes.pdf"
    cbz = library_root / "release-starship.cbz"
    write_epub_fixture(epub)
    write_pdf_fixture(pdf)
    write_comic_fixture(cbz)

    epub_source = REPO_ROOT / "test-data/library/epub/reader-v2.epub"
    pdf_source = REPO_ROOT / "test-data/library/pdf/reading-notes.pdf"
    comic_source = REPO_ROOT / "test-data/library/comics/starship-pages"
    samples = [
        {
            "format": "EPUB",
            **_source_metadata(epub_source, epub),
        },
        {
            "format": "PDF",
            **_source_metadata(pdf_source, pdf),
        },
        {
            "format": "CBZ",
            "sourcePath": str(comic_source),
            "fixturePath": str(cbz),
            "sourceFiles": [
                {
                    "path": str(page),
                    "sha256": sha256_file(page),
                    "sizeBytes": page.stat().st_size,
                }
                for page in sorted(comic_source.glob("*.png"))
            ],
            "fixtureSha256": sha256_file(cbz),
            "sizeBytes": cbz.stat().st_size,
        },
    ]
    samples.extend(_build_audio_samples(library_root, corpus_root))
    return samples


def _run_logged_step(
    label: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout: float,
    lifecycle: FixtureLifecycle,
) -> None:
    lifecycle.stage = label
    lifecycle.check_startup()
    process = start_logged_process(command, cwd=cwd, env=env, log_path=log_path)
    # Register before waiting: timeout, cancellation and wait/stop failures all
    # leave the handle with the same outer lifecycle cleanup owner.
    lifecycle.processes[label] = process
    deadline = min(time.monotonic() + timeout, lifecycle.startup_deadline)
    while True:
        lifecycle.check_startup()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{label} exceeded its {timeout:g} second deadline")
        try:
            exit_code = process.wait(timeout=min(0.25, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    _stop_process(label, process, lifecycle.event_log)
    del lifecycle.processes[label]
    if exit_code != 0:
        raise RuntimeError(
            f"{label} failed with exit code {exit_code}; inspect {log_path.name}"
        )
    lifecycle.check_startup()


def _prepare_database(
    env: dict[str, str], log_path: Path, lifecycle: FixtureLifecycle
) -> None:
    _run_logged_step(
        "prestart",
        [sys.executable, "-m", "app.bootstrap.prestart"],
        cwd=API_ROOT,
        env=env,
        log_path=log_path,
        timeout=120,
        lifecycle=lifecycle,
    )


def _wait_for_web(
    base_url: str,
    process: LoggedProcess,
    lifecycle: FixtureLifecycle,
    timeout: float = 150,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        lifecycle.check_startup()
        if process.poll() is not None:
            raise RuntimeError(
                f"Next process exited early with code {process.returncode}"
            )
        try:
            response = httpx.get(
                f"{base_url}/login",
                follow_redirects=True,
                timeout=3,
            )
            if 200 <= response.status_code < 400:
                return
            last_error = RuntimeError(f"Next returned HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Next did not become ready: {last_error}")


def _stop_process(
    label: str,
    process: LoggedProcess | None,
    event_log: Path,
) -> None:
    if process is None:
        return
    process.stop(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
    # Child output remains in its existing file log; do not duplicate response
    # bodies or credentials into a second error-reporting surface.
    _event(event_log, f"{label}.exit={process.returncode}")


def _validate_lifetime(lifetime_seconds: int) -> None:
    if not 600 <= lifetime_seconds <= 7_800:
        raise ValueError("fixture lifetime must be between 600 and 7800 seconds")


def _wait_for_stop(
    stop_file: Path,
    processes: dict[str, LoggedProcess],
    event_log: Path,
    lifetime_seconds: int = 600,
) -> None:
    _validate_lifetime(lifetime_seconds)
    deadline = time.monotonic() + lifetime_seconds
    while not stop_file.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"browser fixture exceeded its {lifetime_seconds} second lifetime"
            )
        for label, process in processes.items():
            if process.poll() is not None:
                raise RuntimeError(
                    f"{label} exited before the browser completed: {process.returncode}"
                )
        time.sleep(0.25)
    _event(event_log, "stop_file observed")


def _pnpm_command() -> list[str]:
    pnpm_override = os.environ.get("RELEASE_LIVE_PNPM")
    node_override = os.environ.get("RELEASE_LIVE_NODE")
    if pnpm_override:
        pnpm_command = (
            [node_override, pnpm_override] if node_override else [pnpm_override]
        )
    else:
        pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
        if not pnpm:
            raise RuntimeError("pnpm was not found; the live Next fixture cannot start")
        pnpm_command = [pnpm]
    return pnpm_command


def _next_command(web_port: int, web_runtime: str = "development") -> list[str]:
    runtime_arguments = {
        "development": ["dev", "--webpack"],
        "production": ["start"],
    }[web_runtime]
    return [
        *_pnpm_command(),
        "exec",
        "next",
        *runtime_arguments,
        "-H",
        "127.0.0.1",
        "-p",
        str(web_port),
    ]


def _build_production_web(
    env: dict[str, str],
    log_path: Path,
    lifecycle: FixtureLifecycle,
) -> None:
    _run_logged_step(
        "next-build",
        [*_pnpm_command(), "run", "build"],
        cwd=WEB_ROOT,
        env=env,
        log_path=log_path,
        timeout=600,
        lifecycle=lifecycle,
    )


def _application_source_hashes(lifecycle: FixtureLifecycle) -> list[dict[str, str]]:
    """Hash source files, including untracked code, without reading runtime data."""
    lifecycle.check_startup()
    listed = (
        subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *APPLICATION_SOURCE_ROOTS,
                *APPLICATION_SOURCE_FILES,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            timeout=30,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    entries: list[dict[str, str]] = []
    for relative in sorted(set(listed) - {""}):
        lifecycle.check_startup()
        path = REPO_ROOT / relative
        if not (
            relative in APPLICATION_SOURCE_FILES
            or any(relative.startswith(f"{root}/") for root in APPLICATION_SOURCE_ROOTS)
        ):
            continue
        if path.suffix not in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".mjs",
            ".cjs",
            ".css",
            ".scss",
            ".json",
        }:
            continue
        if any(
            part.startswith(".")
            or part
            in {
                "node_modules",
                "__pycache__",
                "tests",
                "fixtures",
                "samples",
                "secrets",
            }
            for part in Path(relative).parts
        ):
            continue
        if path.name in {"secrets.json", "credentials.json"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(REPO_ROOT.resolve()):
            raise ValueError(
                f"application source must stay inside the repository: {relative}"
            )
        if path.is_file():
            entries.append({"path": relative, "sha256": sha256_file(path)})
    return entries


def main() -> int:
    if os.environ.get("RELEASE_LIVE_E2E") != "1":
        raise RuntimeError("This fixture is opt-in; set RELEASE_LIVE_E2E=1")

    args = _parse_args()
    artifact_dir = args.artifact_dir.resolve()
    manifest_path = args.manifest.resolve()
    stop_file = args.stop_file.resolve()
    shutdown_file = args.shutdown_file.resolve()
    if not args.run_id or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in args.run_id
    ):
        raise ValueError(
            "run-id must contain only letters, numbers, hyphens and underscores"
        )
    if any(
        not path.is_relative_to(artifact_dir)
        for path in (manifest_path, stop_file, shutdown_file)
    ):
        raise ValueError(
            "fixture control files must stay inside the evidence directory"
        )
    if (artifact_dir / "runtime").exists() or manifest_path.exists():
        raise ValueError("fixture requires a fresh evidence directory")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.unlink(missing_ok=True)
    # A fresh run can already have a cancellation from the waiting browser.
    # Never erase that signal before preflight observes it.
    shutdown_file.unlink(missing_ok=True)
    event_log = artifact_dir / "fixture.log"
    lifecycle = FixtureLifecycle(
        artifact_dir,
        stop_file,
        shutdown_file,
        time.monotonic() + args.startup_timeout_seconds,
    )
    with _fixture_lifecycle(lifecycle):
        _validate_lifetime(args.lifetime_seconds)
        if not 1 <= args.startup_timeout_seconds <= DEFAULT_STARTUP_TIMEOUT_SECONDS:
            raise ValueError(
                "fixture startup timeout must be between 1 and 1200 seconds"
            )
        lifecycle.check_startup()
        _event(event_log, f"run_id={args.run_id}")
        _event(event_log, f"repo_head={_git_head()}")
        ffprobe_path = _resolve_ffprobe()
        _event(event_log, f"ffprobe_path={ffprobe_path or 'missing'}")
        corpus_root = (
            Path(
                os.environ.get(
                    "RELEASE_LIVE_AUDIO_CORPUS_ROOT", str(DEFAULT_AUDIO_CORPUS_ROOT)
                )
            )
            .expanduser()
            .resolve()
        )
        _event(event_log, f"audio_corpus_root={corpus_root}")

        api_port = _resolve_port(args.api_port, "api_port")
        web_port = _resolve_port(args.web_port, "web_port")
        library_root = artifact_dir / "library"
        storage_root = artifact_dir / "runtime" / "storage"
        inbox = artifact_dir / "runtime" / "downloads" / "inbox"
        ready_file = artifact_dir / "runtime" / "import-worker-ready"
        for directory in (library_root, storage_root, inbox):
            directory.mkdir(parents=True, exist_ok=True)

        lifecycle.stage = "samples"
        lifecycle.check_startup()
        samples = _build_samples(library_root, corpus_root)
        lifecycle.stage = "chapter-engine"
        lifecycle.check_startup()
        # The live catalog requests chapter navigation too; fail before launching
        # clients if the canonical native engine is absent from this test runtime.
        ChapterCore.load()
        chapter_library = os.environ.get("ERMAO_CHAPTER_CORE_LIBRARY")
        lifecycle.stage = "source-snapshot"
        application_sources = _application_source_hashes(lifecycle)
        application_hashes_path = artifact_dir / "application-source-hashes.json"
        _write_json(
            application_hashes_path,
            {
                "roots": APPLICATION_SOURCE_ROOTS,
                "files": APPLICATION_SOURCE_FILES,
                "includesUntracked": True,
                "excludes": "git-ignored files, samples/fixtures/tests, runtime data, hidden files and credentials",
                "entries": application_sources,
            },
        )
        source_patch = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "HEAD",
                "--",
                "apps/api-python/app",
                "apps/web",
                "packages/reader-core",
                "packages/reader-contracts",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        (artifact_dir / "tested-worktree.patch").write_bytes(source_patch)
        source_snapshot = {
            "repoHead": _git_head(),
            "repoRoot": str(REPO_ROOT),
            "sampleOwner": "scripts/python_backend_sample_smoke.py",
            "audioCorpusRoot": str(corpus_root),
            "audioCorpusManifest": str(corpus_root / "公开格式测试 - 来源与校验.md"),
            "ffprobeAvailable": ffprobe_path is not None,
            "ffprobePath": ffprobe_path,
            "samples": samples,
            "fixtureSha256": sha256_file(Path(__file__)),
            "webRuntime": args.web_runtime,
            "testSha256": sha256_file(WEB_ROOT / "e2e" / "release-live.spec.ts"),
            "worktreePatchSha256": sha256_file(artifact_dir / "tested-worktree.patch"),
            "applicationSourceHashesFile": application_hashes_path.name,
            "applicationSourceHashesSha256": sha256_file(application_hashes_path),
            "applicationSourceFileCount": len(application_sources),
            "configuredChapterLibrary": chapter_library,
            "configuredChapterLibrarySha256": sha256_file(Path(chapter_library))
            if chapter_library and Path(chapter_library).is_file()
            else None,
        }
        _write_json(artifact_dir / "source-snapshot.json", source_snapshot)

        runtime_env = dict(os.environ)
        runtime_env.pop("RELEASE_LIVE_PASSWORD", None)
        runtime_env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SESSION_SECRET": secrets.token_urlsafe(32),
                "STORAGE_ROOT": str(storage_root),
                "DOWNLOAD_INBOX_PATH": str(inbox),
                "IMPORT_WORKER_READY_FILE": str(ready_file),
                "IMPORT_QUEUE_INTERVAL_SECONDS": "1",
                "PYTHON_API_ORIGIN": f"http://127.0.0.1:{api_port}",
            }
        )
        runtime_env.pop("FFPROBE_PATH", None)
        if ffprobe_path is not None:
            runtime_env["FFPROBE_PATH"] = ffprobe_path
        database_path = storage_root / "database" / "shuku.sqlite3"
        next_dist_name = f".next-release-live-{args.run_id}"
        next_dist_path = (WEB_ROOT / next_dist_name).resolve()
        if next_dist_path.parent != WEB_ROOT.resolve() or next_dist_path.exists():
            raise ValueError(
                "Next fixture requires a new directory inside the Web workspace"
            )
        next_dist_path.mkdir()
        lifecycle.next_dist_path = next_dist_path
        lifecycle.check_startup()
        _prepare_database(runtime_env, artifact_dir / "prestart.log", lifecycle)
        api_process = start_logged_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
                "--log-level",
                "info",
            ],
            cwd=API_ROOT,
            env=runtime_env,
            log_path=artifact_dir / "api.log",
        )
        lifecycle.processes["api"] = api_process
        lifecycle.stage = "api-ready"
        api_origin = f"http://127.0.0.1:{api_port}"
        wait_for_health(api_origin, api_process)
        lifecycle.check_startup()

        worker_process = start_logged_process(
            [sys.executable, "-m", "app.worker.main"],
            cwd=API_ROOT,
            env=runtime_env,
            log_path=artifact_dir / "worker.log",
        )
        lifecycle.processes["worker"] = worker_process
        lifecycle.stage = "worker-ready"
        wait_for_worker(ready_file, worker_process)
        lifecycle.check_startup()

        _run_logged_step(
            "next-prepare",
            ["node", "scripts/prepare-pdfjs-worker.mjs"],
            cwd=WEB_ROOT,
            env=runtime_env,
            log_path=artifact_dir / "next-prepare.log",
            timeout=120,
            lifecycle=lifecycle,
        )
        _prepare_next_configuration(lifecycle, next_dist_name, args.web_runtime)

        next_env = dict(runtime_env)
        next_env.update(
            {
                "NEXT_DIST_DIR": next_dist_name,
                "PYTHON_API_ORIGIN": api_origin,
                "NEXT_TELEMETRY_DISABLED": "1",
                "NODE_ENV": args.web_runtime,
            }
        )
        if args.web_runtime == "production":
            _build_production_web(next_env, artifact_dir / "next-build.log", lifecycle)
        lifecycle.stage = "next-start"
        lifecycle.check_startup()
        next_command = _next_command(web_port, args.web_runtime)
        _event(event_log, f"next_command={' '.join(next_command)}")
        next_process = start_logged_process(
            next_command,
            cwd=WEB_ROOT,
            env=next_env,
            log_path=artifact_dir / "next.log",
        )
        lifecycle.processes["next"] = next_process
        _wait_for_web(f"http://127.0.0.1:{web_port}", next_process, lifecycle)
        lifecycle.check_startup()
        web_origin = f"http://{args.web_hostname}:{web_port}"

        manifest = {
            "runId": args.run_id,
            "repoHead": source_snapshot["repoHead"],
            "apiOrigin": api_origin,
            "webOrigin": web_origin,
            "webRuntime": args.web_runtime,
            "artifactDir": str(artifact_dir),
            "databasePath": str(database_path),
            "libraryRootPath": str(library_root),
            "libraryName": f"Release live {args.run_id}",
            "organizationMode": "FLAT",
            "audioCorpusRoot": str(corpus_root),
            "audioCorpusManifest": str(corpus_root / "公开格式测试 - 来源与校验.md"),
            "ffprobeAvailable": ffprobe_path is not None,
            "ffprobePath": ffprobe_path,
            "email": os.environ.get(
                "RELEASE_LIVE_EMAIL",
                f"release-live-{args.run_id}@local.invalidx",
            ),
            "samples": samples,
            "processLogs": {
                "fixture": str(event_log),
                "prestart": str(artifact_dir / "prestart.log"),
                "api": str(artifact_dir / "api.log"),
                "worker": str(artifact_dir / "worker.log"),
                "nextPrepare": str(artifact_dir / "next-prepare.log"),
                "nextBuild": str(artifact_dir / "next-build.log")
                if args.web_runtime == "production"
                else None,
                "next": str(artifact_dir / "next.log"),
                "shutdown": str(shutdown_file),
            },
        }
        _write_json(manifest_path, manifest)
        _event(event_log, f"ready manifest={manifest_path}")
        lifecycle.stage = "browser"
        _wait_for_stop(
            stop_file,
            lifecycle.processes,
            event_log,
            args.lifetime_seconds,
        )
        return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        args = None
        try:
            args = _parse_args()
            event_log = args.artifact_dir.resolve() / "fixture.log"
            _event(event_log, traceback.format_exc())
        except OSError as log_error:
            sys.stderr.write(
                f"release live fixture could not write failure log: {log_error}\n"
            )
        raise
    raise SystemExit(exit_code)
