from __future__ import annotations

"""Smoke the production API and the current LibraryImportTask worker.

The fixture library is deliberately isolated in a TemporaryDirectory.  The
library is created through the authenticated HTTP API, which queues a
``SCAN_LIBRARY`` task; the real ``app.worker.main`` process then builds the
Book -> ReadableResource -> ResourceAsset projection.  Reader v4 and media
requests are made with the resource and asset identifiers returned by the
current contracts.
"""

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
from urllib.parse import quote

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from app.core.config import Settings
from app.db.sqlite import create_sqlite_engine
from app.models import (
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
)

SUPPORTED_EXTS = {".epub", ".pdf", ".cbz", ".zip"}
SAMPLE_LIBRARY_NAME = "Sample library"


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


def wait_for_worker(ready_file: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 25
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited early with code {process.returncode}")
        if ready_file.is_file() and ready_file.read_text(encoding="utf-8").strip():
            return
        time.sleep(0.2)
    raise RuntimeError("LibraryImportTask worker did not become ready")


def expect_ok(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AssertionError(
            f"response was not JSON: {response.status_code} {response.text[:200]}"
        ) from exc
    assert 200 <= response.status_code < 300, payload
    assert isinstance(payload, dict), payload
    assert payload.get("ok") is True, payload
    data = payload.get("data")
    assert isinstance(data, dict), payload
    return data


def wait_for_import(
    database_path: Path,
    library_id: str,
    *,
    expected_books: int = 3,
    expected_resources: int = 3,
    expected_assets: int = 3,
) -> None:
    """Observe the canonical task state and projection produced by the worker."""

    engine = create_sqlite_engine(database_path)
    deadline = time.time() + 60
    last_state: dict[str, object] | None = None
    try:
        while time.time() < deadline:
            with Session(engine) as db:
                tasks = list(
                    db.scalars(
                        select(LibraryImportTask)
                        .where(LibraryImportTask.library_id == library_id)
                        .order_by(
                            LibraryImportTask.created_at.asc(),
                            LibraryImportTask.id.asc(),
                        )
                    ).all()
                )
                failed = [
                    f"{task.kind}:{task.error_summary}"
                    for task in tasks
                    if task.state == "FAILED"
                ]
                counts = {
                    "books": int(
                        db.scalar(
                            select(func.count(LibraryBook.id)).where(
                                LibraryBook.library_id == library_id
                            )
                        )
                        or 0
                    ),
                    "resources": int(
                        db.scalar(
                            select(func.count(LibraryReadableResource.id)).where(
                                LibraryReadableResource.library_id == library_id,
                                LibraryReadableResource.import_state == "READY",
                            )
                        )
                        or 0
                    ),
                    "assets": int(
                        db.scalar(
                            select(func.count(LibraryResourceAsset.id)).where(
                                LibraryResourceAsset.library_id == library_id,
                                LibraryResourceAsset.import_state == "READY",
                            )
                        )
                        or 0
                    ),
                }
                last_state = {
                    "tasks": len(tasks),
                    "taskStates": [task.state for task in tasks],
                    **counts,
                }
                if failed:
                    raise RuntimeError(
                        "LibraryImportTask worker failed: " + ", ".join(failed)
                    )
                if (
                    tasks
                    and all(task.state == "SUCCEEDED" for task in tasks)
                    and counts["books"] >= expected_books
                    and counts["resources"] >= expected_resources
                    and counts["assets"] >= expected_assets
                ):
                    return
            time.sleep(0.25)
    finally:
        engine.dispose()
    raise RuntimeError(f"worker did not import sample library in time: {last_state}")


def create_fixture_library(
    client: httpx.Client,
    sample_dir: Path,
) -> str:
    payload = expect_ok(
        client.post(
            "/api/libraries",
            json={
                "name": SAMPLE_LIBRARY_NAME,
                "rootPath": str(sample_dir),
                "organizationMode": "FLAT",
                "enabled": True,
                "ignoreHidden": True,
                "minFileSizeBytes": 1,
            },
        )
    )
    library = payload.get("library")
    assert isinstance(library, dict), payload
    library_id = library.get("id")
    assert isinstance(library_id, str) and library_id, library
    return library_id


def wait_for_task_api(
    client: httpx.Client,
    library_id: str,
) -> None:
    deadline = time.time() + 60
    last_payload: object = None
    while time.time() < deadline:
        response = client.get(
            f"/api/libraries/{library_id}/import-tasks",
            params={"pageSize": 100},
        )
        payload = expect_ok(response)
        last_payload = payload
        tasks = payload.get("tasks")
        assert isinstance(tasks, list), payload
        if any(task.get("state") == "FAILED" for task in tasks):
            raise AssertionError(f"import task API reported failure: {payload}")
        if tasks and all(task.get("state") == "SUCCEEDED" for task in tasks):
            return
        time.sleep(0.25)
    raise RuntimeError(f"import task API did not settle: {last_payload}")


def catalog_resources(client: httpx.Client) -> list[tuple[dict, dict]]:
    catalog = expect_ok(client.get("/api/books", params={"pageSize": 100}))
    books = catalog.get("books")
    assert isinstance(books, list), catalog
    resources: list[tuple[dict, dict]] = []
    for book in books:
        assert isinstance(book, dict), book
        book_id = book.get("id")
        assert isinstance(book_id, str) and book_id, book
        detail = expect_ok(client.get(f"/api/books/{quote(book_id, safe='')}"))
        detail_book = detail.get("book")
        assert isinstance(detail_book, dict), detail
        detail_resources = detail_book.get("resources")
        assert isinstance(detail_resources, list), detail_book
        for resource in detail_resources:
            assert isinstance(resource, dict), resource
            assert resource.get("bookId") == book_id, resource
            resources.append((detail_book, resource))
    assert len(books) == 3, books
    assert len(resources) == 3, resources
    return resources


def validate_imported_sample(
    client: httpx.Client,
    book: dict,
    resource: dict,
    expected_format: str,
) -> None:
    resource_id = resource.get("id")
    book_id = book.get("id")
    assert isinstance(resource_id, str) and resource_id, resource
    assert resource.get("bookId") == book_id, resource
    assert str(resource.get("format", "")).lower() == expected_format, resource

    resource_data = expect_ok(
        client.get(f"/api/resources/{quote(resource_id, safe='')}")
    )
    current_resource = resource_data.get("resource")
    assert isinstance(current_resource, dict), resource_data
    assert current_resource.get("id") == resource_id, current_resource

    asset_data = expect_ok(
        client.get(f"/api/resources/{quote(resource_id, safe='')}/assets")
    )
    assets = asset_data.get("assets")
    assert isinstance(assets, list) and assets, asset_data
    assert asset_data.get("resourceId") == resource_id, asset_data

    bootstrap = expect_ok(
        client.get(f"/api/reader/v4/resources/{quote(resource_id, safe='')}/bootstrap")
    )
    bootstrap_resource = bootstrap.get("resource")
    bootstrap_assets = bootstrap.get("assets")
    assert isinstance(bootstrap_resource, dict), bootstrap
    assert isinstance(bootstrap_assets, list) and bootstrap_assets, bootstrap
    assert bootstrap_resource.get("id") == resource_id, bootstrap
    assert bootstrap_resource.get("bookId") == book_id, bootstrap
    assert all(item.get("resourceId") == resource_id for item in bootstrap_assets)

    primary = next(
        (item for item in bootstrap_assets if item.get("role") == "PRIMARY"),
        None,
    )
    assert isinstance(primary, dict), bootstrap_assets
    asset_id = primary.get("id")
    asset_url = primary.get("url")
    assert isinstance(asset_id, str) and asset_id, primary
    assert asset_url == f"/api/assets/{quote(asset_id, safe='')}", primary

    media = client.get(asset_url, headers={"Range": "bytes=0-4"})
    assert media.status_code == 206, media.text
    assert media.content, "asset Range response was empty"
    assert media.headers.get("content-range", "").startswith("bytes 0-"), media.headers

    if expected_format == "epub":
        assert bootstrap.get("readerType") == "reflowable", bootstrap
        publication = bootstrap.get("publication")
        assert isinstance(publication, dict), bootstrap
        manifest_url = publication.get("manifestUrl")
        positions_url = publication.get("positionsUrl")
        assert isinstance(manifest_url, str), publication
        assert isinstance(positions_url, str), publication
        manifest_response = client.get(manifest_url)
        assert manifest_response.status_code == 200, manifest_response.text
        manifest = manifest_response.json()
        assert isinstance(manifest, dict), manifest
        reading_order = manifest.get("readingOrder")
        assert isinstance(reading_order, list) and reading_order, manifest
        positions_response = client.get(positions_url)
        assert positions_response.status_code == 200, positions_response.text
        positions = positions_response.json()
        assert isinstance(positions, dict) and positions.get("positions"), positions
        href = reading_order[0].get("href")
        assert isinstance(href, str) and href, reading_order[0]
        publication_resource = client.get(
            f"/api/reader/v4/resources/{quote(resource_id, safe='')}/publication/"
            f"{quote(href, safe='/@:;=+$,._~-')}"
        )
        assert publication_resource.status_code == 200, publication_resource.text
        assert publication_resource.content, "publication resource was empty"
        assert media.content.startswith(b"PK\x03\x04"), media.content[:8]
        return

    if expected_format == "pdf":
        assert bootstrap.get("readerType") == "pdf", bootstrap
        assert media.content.startswith(b"%PDF-"), media.content[:8]
        return

    if expected_format == "cbz":
        assert bootstrap.get("readerType") == "comic", bootstrap
        publication = bootstrap.get("publication")
        assert isinstance(publication, dict), bootstrap
        manifest_url = publication.get("manifestUrl")
        assert isinstance(manifest_url, str), publication
        manifest = expect_ok(client.get(manifest_url))
        pages = manifest.get("readingOrder")
        assert isinstance(pages, list) and pages, manifest
        page_index = pages[0].get("pageIndex")
        assert isinstance(page_index, int) and page_index >= 0, pages[0]
        page = client.get(
            f"/api/reader/v4/resources/{quote(resource_id, safe='')}/comic/pages/"
            f"{page_index}"
        )
        assert page.status_code == 200, page.text
        assert page.headers.get("content-type", "").startswith("image/"), page.headers
        assert page.content, "comic page response was empty"
        return

    raise AssertionError(f"unsupported imported format {expected_format!r}")


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


def stop_process(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
    return process.stdout.read() if process.stdout else ""


def run_http_flow(base_url: str, sample_dir: Path, settings: Settings) -> None:
    epub = sample_dir / "sample.epub"
    comic = sample_dir / "sample.cbz"
    pdf = sample_dir / "sample.pdf"
    write_epub_fixture(epub)
    write_comic_fixture(comic)
    write_pdf_fixture(pdf)

    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=15) as client:
        status = expect_ok(client.get("/api/auth/setup/status"))
        assert status["initialized"] is False, status
        setup = expect_ok(
            client.post(
                "/api/auth/setup",
                json={
                    "name": "Sample smoke admin",
                    "email": "smoke@example.com",
                    "password": "runtime-smoke-password",
                },
            )
        )
        assert setup["initialized"] is True
        assert setup["user"]["email"] == "smoke@example.com"

        library_id = create_fixture_library(client, sample_dir)
        wait_for_import(settings.database_path, library_id)
        wait_for_task_api(client, library_id)
        resources = catalog_resources(client)

        by_format = {
            str(resource.get("format", "")).lower(): (book, resource)
            for book, resource in resources
        }
        assert set(by_format) >= {"epub", "pdf", "cbz"}, by_format
        for expected_format in ("epub", "pdf", "cbz"):
            validate_imported_sample(
                client,
                *by_format[expected_format],
                expected_format,
            )

        real_samples = list(discover_real_library_samples())
        if real_samples:
            print(f"Running real-library smoke with {len(real_samples)} sample(s)")
        # Real-library samples are copied into the already-enabled fixture
        # library.  The canonical scan endpoint and worker remain responsible
        # for creating their projections; no importer shortcut is used.
        for index, real_sample in enumerate(real_samples):
            managed_sample = sample_dir / f"real-{index}-{real_sample.name}"
            shutil.copy2(real_sample, managed_sample)
        if real_samples:
            response = client.post(f"/api/libraries/{library_id}/scan")
            expect_ok(response)
            wait_for_import(
                settings.database_path,
                library_id,
                expected_books=3,
                expected_resources=3 + len(real_samples),
                expected_assets=3 + len(real_samples),
            )
            wait_for_task_api(client, library_id)


def main() -> None:
    with TemporaryDirectory(prefix="shuku-python-sample-smoke-") as tmp:
        root = Path(tmp)
        storage_root = root / "storage"
        inbox = root / "downloads" / "inbox"
        sample_dir = root / "library"
        for path in [storage_root, inbox, sample_dir]:
            path.mkdir(parents=True, exist_ok=True)

        settings = Settings(storage_root=str(storage_root))
        api_port = free_port()
        worker_ready_file = root / "import-worker-ready"
        env = {
            **os.environ,
            "SESSION_SECRET": "runtime-smoke-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "DOWNLOAD_INBOX_PATH": str(inbox),
            "IMPORT_WORKER_READY_FILE": str(worker_ready_file),
            "IMPORT_QUEUE_INTERVAL_SECONDS": "1",
        }
        subprocess.run(
            [sys.executable, "-m", "app.bootstrap.prestart"],
            cwd=API_ROOT,
            env=env,
            check=True,
        )
        api_process = subprocess.Popen(
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
                str(api_port),
                "--log-level",
                "warning",
            ],
            cwd=API_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        worker_process: subprocess.Popen[str] | None = None
        try:
            base_url = f"http://127.0.0.1:{api_port}"
            wait_for_health(base_url, api_process)
            worker_process = subprocess.Popen(
                ["uv", "run", "--extra", "dev", "python", "-m", "app.worker.main"],
                cwd=API_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            wait_for_worker(worker_ready_file, worker_process)
            run_http_flow(base_url, sample_dir, settings)
            print("Python backend production-sample smoke ok")
        finally:
            worker_output = stop_process(worker_process) if worker_process else ""
            api_output = stop_process(api_process)
            if worker_output.strip():
                print(worker_output.strip())
            if api_output.strip():
                print(api_output.strip())


if __name__ == "__main__":
    main()
