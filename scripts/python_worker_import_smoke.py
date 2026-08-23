#!/usr/bin/env python3
"""Smoke the production ContinueImport worker against a fresh SQLite database."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from app.bootstrap.readable_resource_pipeline import (  # noqa: E402
    continue_library_import,
)
from app.core.config import Settings  # noqa: E402
from app.db.bootstrap import bootstrap_database  # noqa: E402
from app.db.sqlite import create_sqlite_engine  # noqa: E402
from app.models import (  # noqa: E402
    Library,
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)


def write_epub_fixture(path: Path) -> None:
    title = "ContinueImport smoke book"
    chapter = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(title)}</title></head>
<body><h1>{escape(title)}</h1><p>worker smoke</p></body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{escape(title)}</dc:title><dc:creator>smoke</dc:creator>
  </metadata><manifest/><spine/>
</package>
""",
        )
        archive.writestr("OEBPS/chapter.xhtml", chapter)


def setup_database(storage_root: Path, monitor_root: Path) -> str:
    settings = Settings(storage_root=str(storage_root))
    engine = create_sqlite_engine(settings.database_path)
    bootstrap_database(engine, settings)
    with Session(engine) as db:
        db.add(
            Library(
                id="continue-import-smoke",
                name="ContinueImport smoke",
                root_path=str(monitor_root),
                organization_mode="FLAT",
                enabled=True,
                ignore_hidden=True,
                min_file_size_bytes=1,
            )
        )
        db.commit()
        continue_library_import(db, "continue-import-smoke")
    engine.dispose()
    return f"sqlite+pysqlite:///{settings.database_path}"


def wait_for_ready(ready_file: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited early with code {process.returncode}")
        if ready_file.is_file() and ready_file.read_text(encoding="utf-8").strip().isdigit():
            return
        time.sleep(0.2)
    raise RuntimeError("worker did not create ready file")


def wait_for_import(database_url: str) -> None:
    engine = create_engine(database_url)
    deadline = time.time() + 20
    last_state: dict[str, object] | None = None
    try:
        while time.time() < deadline:
            with Session(engine) as db:
                task = db.scalar(
                    select(LibraryImportTask)
                    .where(LibraryImportTask.library_id == "continue-import-smoke")
                    .order_by(LibraryImportTask.created_at.desc(), LibraryImportTask.id.desc())
                )
                counts = {
                    "sourceNodes": db.scalar(
                        select(LibrarySourceNode.id).where(
                            LibrarySourceNode.library_id == "continue-import-smoke"
                        ).limit(1)
                    )
                    is not None,
                    "books": db.scalar(
                        select(LibraryBook.id).where(
                            LibraryBook.library_id == "continue-import-smoke"
                        ).limit(1)
                    )
                    is not None,
                    "resources": db.scalar(
                        select(LibraryReadableResource.id).where(
                            LibraryReadableResource.library_id == "continue-import-smoke"
                        ).limit(1)
                    )
                    is not None,
                    "assets": db.scalar(
                        select(LibraryResourceAsset.id)
                        .where(
                            LibraryResourceAsset.library_id
                            == "continue-import-smoke"
                        )
                        .limit(1)
                    )
                    is not None,
                }
                last_state = {
                    "task": task.state if task is not None else None,
                    **counts,
                }
                if (
                    task is not None
                    and task.state == "SUCCEEDED"
                    and all(counts.values())
                ):
                    return
                if task is not None and task.state == "FAILED":
                    raise RuntimeError(
                        f"ContinueImport worker failed: {task.error_summary}"
                    )
            time.sleep(0.25)
    finally:
        engine.dispose()
    raise RuntimeError(f"worker did not import EPUB in time: {last_state}")


def main() -> None:
    with TemporaryDirectory(prefix="worker-import-smoke-") as temporary:
        root = Path(temporary)
        monitor_root = root / "monitor"
        storage_root = root / "storage"
        ready_file = root / "import-worker-ready"
        monitor_root.mkdir(parents=True)
        storage_root.mkdir(parents=True)
        write_epub_fixture(monitor_root / "watched.epub")

        database_url = setup_database(storage_root, monitor_root)
        env = {
            **os.environ,
            "SESSION_SECRET": "runtime-smoke-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "IMPORT_WORKER_READY_FILE": str(ready_file),
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
            wait_for_import(database_url)
            print("ContinueImport worker smoke ok")
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
