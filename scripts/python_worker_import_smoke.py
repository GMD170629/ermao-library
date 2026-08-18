from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import mkdtemp

from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from app.core.config import Settings  # noqa: E402
from app.db.bootstrap import bootstrap_database  # noqa: E402
from app.db.sqlite import create_sqlite_engine  # noqa: E402
from tests.test_worker_importer import write_epub_fixture  # noqa: E402


def setup_database(storage_root: Path, monitor_root: Path) -> str:
    settings = Settings(storage_root=str(storage_root))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    with engine.begin() as db:
        db.execute(
            text(
                """INSERT INTO Library (
                    id, name, rootPath, enabled, ignoreHidden, minFileSizeBytes,
                    createdAt, updatedAt
                ) VALUES (
                    'monitor-smoke', 'Smoke Monitor', :root_path, 1, 1, 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )"""
            ),
            {"root_path": str(monitor_root)},
        )
    engine.dispose()
    return f"sqlite+pysqlite:///{settings.database_path}"


def wait_for_ready(ready_file: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited early with code {process.returncode}")
        if (
            ready_file.exists()
            and ready_file.read_text(encoding="utf-8").strip().isdigit()
        ):
            return
        time.sleep(0.2)
    raise RuntimeError("worker did not create ready file")


def wait_for_import(database_url: str, source_path: Path) -> None:
    engine = create_engine(database_url)
    deadline = time.time() + 20
    last_state = None
    try:
        while time.time() < deadline:
            with engine.connect() as conn:
                task = (
                    conn.execute(
                        text(
                            "SELECT status, message, errorSummary FROM ImportTask WHERE sourcePath = :source_path ORDER BY createdAt DESC LIMIT 1"
                        ),
                        {"source_path": str(source_path)},
                    )
                    .mappings()
                    .first()
                )
                work_count = (
                    conn.execute(
                        text("SELECT COUNT(*) FROM LibraryWork WHERE origin = 'WATCH'")
                    ).scalar()
                    or 0
                )
                unit_count = (
                    conn.execute(
                        text("SELECT COUNT(*) FROM LibraryReadingUnit")
                    ).scalar()
                    or 0
                )
                last_state = {
                    "task": dict(task) if task else None,
                    "workCount": work_count,
                    "unitCount": unit_count,
                }
                if (
                    task
                    and task["status"] == "COMPLETED"
                    and work_count == 1
                    and unit_count == 2
                ):
                    return
                if task and task["status"] == "FAILED":
                    raise RuntimeError(f"worker import failed: {task}")
            time.sleep(0.25)
    finally:
        engine.dispose()
    raise RuntimeError(f"worker did not import monitored EPUB in time: {last_state}")


def main() -> None:
    temp_parent = REPO_ROOT / "tmp-worker-smoke"
    temp_parent.mkdir(exist_ok=True)
    root = Path(mkdtemp(prefix="worker-import-smoke-", dir=temp_parent))
    try:
        monitor_root = root / "monitor"
        storage_root = root / "storage"
        ready_file = root / "scan-worker-ready"
        for path in [monitor_root, storage_root]:
            path.mkdir(parents=True, exist_ok=True)

        database_url = setup_database(storage_root, monitor_root)
        env = {
            **os.environ,
            "SESSION_SECRET": "runtime-smoke-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "SCAN_WORKER_READY_FILE": str(ready_file),
            "MONITOR_REFRESH_INTERVAL_MS": "1000",
            "MONITOR_FILE_STABLE_DELAY_MS": "100",
        }

        process = subprocess.Popen(
            ["uv", "run", "--extra", "dev", "python", "-m", "app.worker.main"],
            cwd=API_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_ready(ready_file, process)
            source = monitor_root / "watched.epub"
            write_epub_fixture(source)
            wait_for_import(database_url, source)
            print("Python worker monitored-import smoke ok")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            output = process.stdout.read() if process.stdout else ""
            interesting = "\n".join(
                line for line in output.splitlines() if "[import-worker]" in line
            ).strip()
            if interesting:
                print(interesting)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
