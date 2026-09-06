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
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

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
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _event(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(message.rstrip() + "\n")


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
                "durationClaim": "short format fixture; no long-duration claim",
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


def _prepare_database(env: dict[str, str], log_path: Path) -> None:
    with log_path.open("w", encoding="utf-8") as stream:
        subprocess.run(
            [sys.executable, "-m", "app.bootstrap.prestart"],
            cwd=API_ROOT,
            env=env,
            check=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=120,
        )


def _wait_for_web(base_url: str, process: LoggedProcess, timeout: float = 150) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
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
) -> bool:
    if process is None:
        return True
    try:
        output = process.stop(timeout=12)
        _event(event_log, f"{label}.exit={process.returncode}")
        if output.strip():
            _event(event_log, f"[{label} log]\n{output.rstrip()}")
        return True
    except (OSError, TimeoutError, subprocess.SubprocessError) as exc:
        _event(event_log, f"{label}.stop_error={exc}")
        return False


def _wait_for_stop(
    stop_file: Path,
    processes: dict[str, LoggedProcess],
    event_log: Path,
) -> None:
    deadline = time.monotonic() + 600
    while not stop_file.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("browser fixture exceeded its 600 second lifetime")
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


def _build_production_web(env: dict[str, str], log_path: Path) -> None:
    build = start_logged_process(
        [*_pnpm_command(), "run", "build"],
        cwd=WEB_ROOT,
        env=env,
        log_path=log_path,
    )
    try:
        if build.wait(timeout=600) != 0:
            raise RuntimeError("Production Web build failed; inspect next-build.log")
    finally:
        build.stop(timeout=12)


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
    stop_file.unlink(missing_ok=True)
    shutdown_file.unlink(missing_ok=True)
    event_log = artifact_dir / "fixture.log"
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

    samples = _build_samples(library_root, corpus_root)
    # The live catalog requests chapter navigation too; fail before launching
    # clients if the canonical native engine is absent from this test runtime.
    ChapterCore.load()
    chapter_library = os.environ.get("ERMAO_CHAPTER_CORE_LIBRARY")
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
    api_process: LoggedProcess | None = None
    worker_process: LoggedProcess | None = None
    next_process: LoggedProcess | None = None
    next_dist_name = f".next-release-live-{args.run_id}"
    next_dist_path = (WEB_ROOT / next_dist_name).resolve()
    if next_dist_path.parent != WEB_ROOT.resolve() or next_dist_path.exists():
        raise ValueError(
            "Next fixture requires a new directory inside the Web workspace"
        )
    try:
        _prepare_database(runtime_env, artifact_dir / "prestart.log")
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
        api_origin = f"http://127.0.0.1:{api_port}"
        wait_for_health(api_origin, api_process)

        worker_process = start_logged_process(
            [sys.executable, "-m", "app.worker.main"],
            cwd=API_ROOT,
            env=runtime_env,
            log_path=artifact_dir / "worker.log",
        )
        wait_for_worker(ready_file, worker_process)

        prepare_worker = subprocess.run(
            ["node", "scripts/prepare-pdfjs-worker.mjs"],
            cwd=WEB_ROOT,
            env=runtime_env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        (artifact_dir / "next-prepare.log").write_text(
            prepare_worker.stdout + prepare_worker.stderr,
            encoding="utf-8",
        )
        if prepare_worker.returncode != 0:
            raise RuntimeError(
                f"Next PDF worker preparation failed: {prepare_worker.returncode}"
            )

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
            _build_production_web(next_env, artifact_dir / "next-build.log")
        next_command = _next_command(web_port, args.web_runtime)
        _event(event_log, f"next_command={' '.join(next_command)}")
        next_process = start_logged_process(
            next_command,
            cwd=WEB_ROOT,
            env=next_env,
            log_path=artifact_dir / "next.log",
        )
        _wait_for_web(f"http://127.0.0.1:{web_port}", next_process)
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
        _wait_for_stop(
            stop_file,
            {"api": api_process, "worker": worker_process, "next": next_process},
            event_log,
        )
        return 0
    finally:
        processes_stopped = all(
            (
                _stop_process("next", next_process, event_log),
                _stop_process("worker", worker_process, event_log),
                _stop_process("api", api_process, event_log),
            )
        )
        if processes_stopped:
            shutdown_file.write_text("stopped\n", encoding="utf-8")
            _event(event_log, f"shutdown_complete={shutdown_file}")
        else:
            _event(
                event_log,
                "shutdown_complete not written because a child did not stop cleanly",
            )
        if next_dist_path.exists() and next_dist_path.parent == WEB_ROOT.resolve():
            try:
                shutil.rmtree(next_dist_path)
            except OSError as exc:
                _event(event_log, f"next_dist_cleanup_error={exc}")


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
