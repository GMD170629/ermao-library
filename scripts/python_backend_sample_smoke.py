from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from app.bootstrap.imports import (
    claim_next_import_task,
    process_import_task,
)
from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.db.sqlite import create_sqlite_engine
from app.models.common import db_timestamp
from app.models.library import Library
from app.modules.imports.infrastructure.scan_batch_store import (
    load_scan_candidate_projection,
    prepare_scan_candidate_batch,
    prepare_scan_sources,
    write_prepared_scan_candidate_batch,
)

SUPPORTED_EXTS = {".epub", ".pdf", ".cbz", ".zip"}
SAMPLE_LIBRARY_ID = "sample-library"


def write_epub_fixture(path: Path) -> None:
    shutil.copyfile(REPO_ROOT / "test-data/library/epub/reader-v2.epub", path)


def write_pdf_fixture(path: Path) -> None:
    shutil.copyfile(REPO_ROOT / "test-data/library/pdf/reading-notes.pdf", path)


def write_comic_fixture(path: Path) -> None:
    pages_root = REPO_ROOT / "test-data/library/comics/starship-pages"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for page in sorted(pages_root.glob("*.png")):
            archive.write(page, page.name)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 20
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"uvicorn exited early with code {process.returncode}")
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=2)
            payload = response.json()
            if (
                response.status_code == 200
                and payload.get("ok") is True
                and payload.get("data", {}).get("status") == "ok"
            ):
                return
            last_error = RuntimeError(
                f"unexpected health response {response.status_code}: {payload}"
            )
        # Health polling must retain the last transport or decoding failure
        # while the independently managed sample process is still starting.
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"health check timed out: {last_error}")


def expect_ok(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"response was not JSON: {response.status_code} {response.text[:200]}"
        ) from exc
    assert 200 <= response.status_code < 300, payload
    assert payload.get("ok") is True, payload
    return payload["data"]


def import_sample(path: Path, settings: Settings) -> dict:
    engine = create_sqlite_engine(settings.database_path)
    try:
        sources = prepare_scan_sources(
            (path,),
            library_root=path.parent,
            organization_mode="FLAT",
        )
        with Session(engine) as projection_db:
            projection = load_scan_candidate_projection(
                projection_db,
                sources,
                library_id=SAMPLE_LIBRARY_ID,
            )
        prepared = prepare_scan_candidate_batch(
            sources,
            projection,
            library_id=SAMPLE_LIBRARY_ID,
            now_ms=now_timestamp_ms(),
            now=db_timestamp(),
        )
        with Session(engine) as enqueue_db:
            scan_result = write_prepared_scan_candidate_batch(enqueue_db, prepared)
            assert scan_result.queued_count == 1, scan_result
            enqueue_db.commit()
        with Session(engine) as db:
            task = claim_next_import_task(db, "sample-smoke", 900)
            assert task is not None
            result = process_import_task(db, settings, task)
        assert result.volume_id is not None
        return {
            "versionId": result.version_id,
            "volumeId": result.volume_id,
            "format": result.format,
            "type": result.type,
        }
    finally:
        engine.dispose()


def validate_imported_sample(
    client: httpx.Client, result: dict, expected_ext: str
) -> None:
    fmt = result["format"]
    bootstrap = expect_ok(
        client.get(f"/api/reader/v4/volumes/{result['volumeId']}/bootstrap")
    )
    assert bootstrap["volume"]["id"] == result["volumeId"]
    assert bootstrap["version"]["id"] == result["versionId"]
    if fmt == "epub":
        assert bootstrap["readerType"] == "reflowable"
        assert bootstrap["availableVolumes"][0]["id"] == result["volumeId"]
        assert bootstrap["units"], bootstrap
        epub_file = client.get(
            f"/api/volumes/{result['volumeId']}/file",
            headers={"Range": "bytes=0-3"},
        )
        assert epub_file.status_code == 206, epub_file.text
        assert epub_file.content == b"PK\x03\x04"
        return
    if fmt == "pdf":
        assert bootstrap["readerType"] == "pdf"
        pdf_file = client.get(
            f"/api/volumes/{result['volumeId']}/file",
            headers={"Range": "bytes=0-4"},
        )
        assert pdf_file.status_code == 206, pdf_file.text
        assert pdf_file.content == b"%PDF-"
        return
    if fmt in {"cbz", "zip"} or result["type"] == "comic":
        assert bootstrap["readerType"] == "comic"
        assert bootstrap["volume"]["pageCount"] >= 1, bootstrap
        pages = expect_ok(client.get(f"/api/volumes/{result['volumeId']}/pages"))
        assert pages["total"] >= 1, pages
        page = client.get(f"/api/volumes/{result['volumeId']}/pages/1")
        assert page.status_code == 200, page.text
        assert page.headers["content-type"].startswith("image/"), page.headers
        assert page.content, "comic page response was empty"
        return
    raise AssertionError(f"unsupported imported format {fmt!r} for {expected_ext}")


def run_http_flow(base_url: str, sample_dir: Path, settings: Settings) -> None:
    epub = sample_dir / "sample.epub"
    comic = sample_dir / "sample.zip"
    pdf = sample_dir / "sample.pdf"
    write_epub_fixture(epub)
    write_comic_fixture(comic)
    write_pdf_fixture(pdf)

    engine = create_sqlite_engine(settings.database_path)
    try:
        with Session(engine) as db, db.begin():
            db.add(
                Library(
                    id=SAMPLE_LIBRARY_ID,
                    name="Sample library",
                    root_path=str(sample_dir),
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
    finally:
        engine.dispose()

    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=10) as client:
        status = expect_ok(client.get("/api/auth/setup/status"))
        assert status["initialized"] is False
        setup = expect_ok(
            client.post(
                "/api/auth/setup",
                json={
                    "email": "smoke@example.com",
                    "password": "runtime-smoke-password",
                },
            )
        )
        assert setup["initialized"] is True
        assert setup["user"]["email"] == "smoke@example.com"

        epub_result = import_sample(epub, settings)
        validate_imported_sample(client, epub_result, ".epub")

        comic_result = import_sample(comic, settings)
        validate_imported_sample(client, comic_result, ".zip")

        pdf_result = import_sample(pdf, settings)
        validate_imported_sample(client, pdf_result, ".pdf")

        real_samples = list(discover_real_library_samples())
        if real_samples:
            print(f"Running real-library smoke with {len(real_samples)} sample(s)")
        for index, real_sample in enumerate(real_samples):
            managed_sample = sample_dir / f"real-{index}-{real_sample.name}"
            shutil.copy2(real_sample, managed_sample)
            result = import_sample(managed_sample, settings)
            validate_imported_sample(client, result, real_sample.suffix.lower())


def discover_real_library_samples() -> Iterable[Path]:
    root_value = os.environ.get("PYTHON_REAL_LIBRARY_SAMPLE_DIR")
    required = os.environ.get("REQUIRE_REAL_LIBRARY_SAMPLE_DIR") == "true"
    if not root_value:
        if required:
            raise RuntimeError(
                "PYTHON_REAL_LIBRARY_SAMPLE_DIR is required for real-library smoke"
            )
        return []
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"PYTHON_REAL_LIBRARY_SAMPLE_DIR is not a directory: {root}")
    max_count = max(1, int(os.environ.get("PYTHON_REAL_LIBRARY_SAMPLE_LIMIT") or "6"))
    max_bytes = int(
        os.environ.get("PYTHON_REAL_LIBRARY_SAMPLE_MAX_BYTES")
        or str(1024 * 1024 * 1024)
    )
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(found) >= max_count:
            break
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > max_bytes:
            continue
        found.append(path)
    if required and not found:
        raise RuntimeError(f"no supported EPUB/CBZ/ZIP/PDF samples found under {root}")
    return found


def main() -> None:
    with TemporaryDirectory(prefix="shuku-python-sample-smoke-") as tmp:
        root = Path(tmp)
        monitor_root = root / "monitor"
        storage_root = root / "storage"
        inbox = root / "downloads" / "inbox"
        sample_dir = monitor_root / "samples"
        for path in [monitor_root, storage_root, inbox, sample_dir]:
            path.mkdir(parents=True, exist_ok=True)

        settings = Settings(storage_root=str(storage_root))
        port = free_port()
        env = {
            **os.environ,
            "SESSION_SECRET": "runtime-smoke-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "DOWNLOAD_INBOX_PATH": str(inbox),
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "app.bootstrap.prestart",
            ],
            cwd=API_ROOT,
            env=env,
            check=True,
        )
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "--extra",
                "dev",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=API_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            wait_for_health(base_url, process)
            run_http_flow(base_url, sample_dir, settings)
            print("Python backend production-sample smoke ok")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            output = process.stdout.read() if process.stdout else ""
            if output.strip():
                print(output.strip())


if __name__ == "__main__":
    main()
