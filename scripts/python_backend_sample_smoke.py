# ruff: noqa: S106

from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from appv2.composition.container import Container, build_container  # noqa: E402
from appv2.platform.config import Settings  # noqa: E402
from appv2.platform.database.migrations import migrate  # noqa: E402

SUPPORTED_EXTENSIONS = {
    ".epub",
    ".pdf",
    ".cbz",
    ".cbr",
    ".txt",
    ".mobi",
    ".azw3",
    ".mp3",
    ".m4a",
    ".m4b",
    ".flac",
    ".ogg",
    ".wav",
}


def actor_id(container: Container) -> uuid.UUID:
    if container.accounts.setup_required():
        return container.accounts.setup(
            email=f"sample-smoke-{uuid.uuid4().hex}@example.com",
            display_name="Sample Smoke",
            password="sample-smoke-password-at-least-20-characters",
            locale="en-US",
        ).account.id
    users, total = container.accounts.list_users(page=1, page_size=1)
    if total < 1:
        raise RuntimeError("account repository reported an inconsistent user count")
    return users[0].id


def import_one(container: Container, user_id: uuid.UUID, path: Path) -> None:
    accepted = container.ingestion.enqueue(
        source_path=str(path),
        requested_by=user_id,
        idempotency_key=f"sample-smoke-{uuid.uuid4().hex}",
    )
    if not container.ingestion_worker.run_once("sample-smoke"):
        raise RuntimeError(f"worker did not claim {path.name}")
    jobs, _ = container.ingestion.list_jobs(page=1, page_size=200, status=None)
    job = next(item for item in jobs if item.id == accepted.job_id)
    if job.status != "completed" or job.result_id is None:
        raise RuntimeError(f"sample import failed for {path.name}: {job}")
    target = container.reading.bootstrap(user_id=user_id, edition_id=job.result_id)[0]
    expected_format = (
        "audio"
        if path.suffix.lower() in {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".wav"}
        else path.suffix.lower().removeprefix(".")
    )
    if target.format != expected_format:
        raise RuntimeError(
            f"sample {path.name} resolved to {target.format}, expected {expected_format}"
        )
    stream = container.reading.resource(
        user_id=user_id,
        edition_id=job.result_id,
        requested_range=None,
    )
    try:
        if b"".join(stream.iterator) != path.read_bytes():
            raise RuntimeError(f"streamed bytes differ for {path.name}")
    finally:
        stream.close()


def real_samples() -> Iterable[Path]:
    root_value = os.getenv("PYTHON_REAL_LIBRARY_SAMPLE_DIR")
    required = os.getenv("REQUIRE_REAL_LIBRARY_SAMPLE_DIR") == "true"
    if not root_value:
        if required:
            raise RuntimeError("PYTHON_REAL_LIBRARY_SAMPLE_DIR is required")
        return ()
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"sample directory does not exist: {root}")
    limit = max(1, int(os.getenv("PYTHON_REAL_LIBRARY_SAMPLE_LIMIT", "6")))
    maximum = int(os.getenv("PYTHON_REAL_LIBRARY_SAMPLE_MAX_BYTES", str(1024**3)))
    samples = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and 0 < path.stat().st_size <= maximum
    ][:limit]
    if required and not samples:
        raise RuntimeError(f"no supported samples found under {root}")
    return samples


def main() -> None:
    database_url = os.getenv("APPV2_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "APPV2_TEST_DATABASE_URL or DATABASE_URL must point to "
            "an isolated PostgreSQL 18 database"
        )
    with TemporaryDirectory(prefix="shuku-appv2-samples-") as temporary:
        root = Path(temporary)
        monitor_root = root / "monitor"
        storage_root = root / "storage"
        samples_root = monitor_root / "samples"
        samples_root.mkdir(parents=True)
        fixtures = {
            "sample.txt": b"Shuku Starship appv2\n",
            "sample.epub": b"PK\x03\x04appv2-epub-smoke",
            "sample.pdf": b"%PDF-1.7\n% appv2 smoke\n",
            "sample.cbz": b"PK\x03\x04appv2-comic-smoke",
            "sample.mp3": b"ID3appv2-audio-smoke",
        }
        paths: list[Path] = []
        for name, content in fixtures.items():
            path = samples_root / name
            path.write_bytes(content)
            paths.append(path)
        for index, source in enumerate(real_samples()):
            destination = samples_root / f"real-{index}-{source.name}"
            shutil.copy2(source, destination)
            paths.append(destination)

        settings = Settings(
            database_url=database_url,
            session_secret="sample-smoke-session-secret-at-least-32-characters",
            storage_root=storage_root,
            monitor_root=monitor_root,
            environment="test",
        )
        migrate(settings.database_dsn, API_ROOT)
        container = build_container(settings)
        try:
            user_id = actor_id(container)
            for path in paths:
                import_one(container, user_id, path)
            print(f"appv2 production-sample smoke ok ({len(paths)} files)")
        finally:
            container.close()


if __name__ == "__main__":
    main()
