#!/usr/bin/env python3
"""Host smoke of the real built application. Run with the API virtualenv Python.

Requires `pnpm --filter @shuku/web build` and free ports 8000, 3001, 18300.
This does not replace Linux container, PID 1 or network-isolation acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for port in (8000, 3001, 18300):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    standalone = ROOT / "apps/web/.next/standalone"
    if not (standalone / "apps/web/server.js").is_file():
        raise RuntimeError("Build the Web production artifact first")
    with tempfile.TemporaryDirectory(prefix="shuku-runtime-smoke-") as temporary:
        scratch = Path(temporary).resolve()
        seed, storage = scratch / "image", scratch / "storage"
        shutil.copytree(standalone, seed, symlinks=True)
        for source, target in (
            (ROOT / "apps/web/.next/static", seed / "apps/web/.next/static"),
            (ROOT / "apps/web/public", seed / "apps/web/public"),
            (ROOT / "apps/api-python/app", seed / "apps/api-python/app"),
        ):
            shutil.copytree(source, target, dirs_exist_ok=True)
        (seed / "scripts").mkdir(exist_ok=True)
        for name in ("start-unified-app.sh", "unified-http-gateway.mjs"):
            shutil.copy2(ROOT / "scripts" / name, seed / "scripts" / name)
        storage.mkdir()
        protected = (
            storage / "covers/fixture",
            scratch / "books/fixture",
            storage / "configuration",
        )
        for file in protected:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"preserve me")
        runtime = storage / "runtime"
        ready = scratch / "worker-ready"
        environment = {
            **os.environ,
            "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
            "STORAGE_ROOT": str(storage),
            "SHUKU_IMAGE_ROOT": str(seed),
            "HOSTNAME": "127.0.0.1",
            "PORT": "18300",
            "NEXT_INTERNAL_PORT": "3001",
            "IMPORT_WORKER_READY_FILE": str(ready),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        environment.pop("SESSION_SECRET", None)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        secret_digest = None
        database_inode = None
        for attempt in range(2):
            log = scratch / f"run-{attempt}.log"
            with log.open("w") as output:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / "scripts/container-entry.py")],
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 60
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(log.read_text())
                        try:
                            with opener.open(
                                "http://127.0.0.1:18300/api/health", timeout=1
                            ) as response:
                                health = json.load(response)
                            with opener.open(
                                "http://127.0.0.1:18300/login", timeout=2
                            ) as response:
                                assert response.status == 200
                                assert b"<html" in response.read()
                            if ready.is_file():
                                break
                        except OSError:
                            pass
                        if time.monotonic() >= deadline:
                            raise RuntimeError(log.read_text())
                        time.sleep(0.2)
                    worker_pid = int(ready.read_text())
                    command = subprocess.check_output(
                        ["ps", "-p", str(worker_pid), "-o", "command="], text=True
                    )
                    assert "app.worker.main" in command
                    # lsof resolves the live Worker's cwd, not a configured string.
                    cwd = subprocess.check_output(
                        ["lsof", "-a", "-p", str(worker_pid), "-d", "cwd", "-Fn"],
                        text=True,
                    )
                    assert str(runtime / "apps/api-python") in cwd
                    database = storage / "database/shuku.sqlite3"
                    with sqlite3.connect(database) as connection:
                        assert connection.execute(
                            "SELECT version_num FROM alembic_version"
                        ).fetchone()
                        if attempt == 0:
                            connection.execute("PRAGMA user_version=321")
                        else:
                            assert connection.execute(
                                "PRAGMA user_version"
                            ).fetchone() == (321,)
                    digest = hashlib.sha256(
                        (storage / "secrets/session-secret").read_bytes()
                    ).hexdigest()
                    if attempt == 0:
                        secret_digest, database_inode = digest, database.stat().st_ino
                    else:
                        assert (digest, database.stat().st_ino) == (
                            secret_digest,
                            database_inode,
                        )
                        assert (
                            runtime / "retained-marker"
                        ).read_text() == "keep newer runtime"
                    assert all(
                        file.read_bytes() == b"preserve me" for file in protected
                    )
                    print(
                        f"run {attempt + 1}: API={health}, Web=200, Worker cwd=runtime",
                        flush=True,
                    )
                finally:
                    process.terminate()
                    process.wait(timeout=30)
                assert process.returncode == 143
                assert not ready.exists()
                contents = log.read_text()
                assert contents.index("prestart outcome=success") < contents.index(
                    "Application startup complete"
                )
            if attempt == 0:
                (runtime / "retained-marker").write_text("keep newer runtime")
                shutil.rmtree(seed)
        print(
            "PASS: real services restarted without image seed; database, secret and file sentinels retained"
        )


if __name__ == "__main__":
    main()
