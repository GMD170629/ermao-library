#!/usr/bin/env python3
"""Explicit A -> B smoke against a prebuilt image, using disposable Docker data."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image",
        required=True,
        help="Locally built production image; never pulled by this script",
    )
    args = parser.parse_args()
    docker("image", "inspect", args.image)
    name = "shuku-update-" + uuid.uuid4().hex[:10]
    # Use Docker's native Linux volume for SQLite and flock, not a macOS file share.
    volume = name + "-storage"
    docker("volume", "create", volume)
    with tempfile.TemporaryDirectory(prefix="shuku-real-update-") as directory:
        root = Path(directory)
        storage, books = root / "storage", root / "books"
        storage.mkdir()
        books.mkdir()
        (books / "book.txt").write_text("book")
        sentinel = root / "acceptance-only"
        sentinel.touch()
        container = docker(
            "run",
            "--pull=never",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::3000",
            "-v",
            f"{volume}:/app/storage",
            "-v",
            f"{books}:/books",
            "-v",
            f"{ROOT}:/tooling:ro",
            "-v",
            f"{sentinel}:/acceptance-only:ro",
            args.image,
        )
        try:
            port = docker("port", name, "3000/tcp").rsplit(":", 1)[1]
            base = f"http://127.0.0.1:{port}"
            client = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )

            def request(path, payload=None):
                data = json.dumps(payload).encode() if payload is not None else None
                return client.open(
                    urllib.request.Request(
                        base + path,
                        data=data,
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=3,
                )

            def wait_for(predicate, seconds=180):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    try:
                        if predicate():
                            return
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.5)
                raise AssertionError("acceptance timed out")

            def healthy():
                with request("/api/health") as response:
                    return response.status == 200

            wait_for(healthy)
            with request(
                "/api/auth/setup",
                {
                    "email": "acceptance@example.com",
                    "password": "Acceptance-password-42",
                    "name": "Acceptance",
                },
            ) as response:
                assert response.status == 201
            image = docker("inspect", "-f", "{{.Image}}", name)
            seed_version = docker(
                "exec",
                name,
                "python",
                "-c",
                'import json;print(json.load(open("/opt/shuku-image/application.json"))["version"])',
            )
            secret = docker("exec", name, "cat", "/app/storage/secrets/session-secret")
            # Actual program paths and old process identities, excluding exec helpers.
            old_pids = json.loads(
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    'import pathlib,json,os;print(json.dumps([int(p.name) for p in pathlib.Path("/proc").iterdir() if p.name.isdigit() and int(p.name)>1 and int(p.name)!=os.getpid() and (p/"cmdline").exists() and any(x in (p/"cmdline").read_bytes() for x in [b"app.main:app",b"app.worker.main",b"/app/storage/runtime/apps/web/server.js",b"/app/storage/runtime/scripts/start-unified-app.sh",b"/app/storage/runtime/scripts/unified-http-gateway.mjs"]) ]))',
                )
            )
            fixture = docker(
                "exec",
                "-w",
                "/app/storage/runtime/apps/api-python",
                name,
                "python",
                "/tooling/scripts/container_update_fixture.py",
            )
            target = json.loads(fixture.splitlines()[-1])["target"]
            with request("/api/updates/install", {"version": target}) as response:
                assert response.status == 202

            def installed():
                state = json.loads(
                    docker(
                        "exec", name, "cat", "/app/storage/update-tmp/preparation.json"
                    )
                )
                if state["phase"] == "failed":
                    raise RuntimeError(f"actual installation failed: {state}")
                return state["phase"] == "success"

            wait_for(installed, 300)
            docker("cp", name + ":/app/storage/.", str(storage))
            with request("/api/health") as response:
                assert response.headers["X-Acceptance-Code"] == "B"
            assert docker("inspect", "-f", "{{.Id}}", name) == container
            assert docker("inspect", "-f", "{{.Image}}", name) == image
            assert not (storage / "runtime/obsolete-acceptance-file").exists()
            assert (storage / "runtime/.initialized").read_text() == "1\n"
            assert (storage / "secrets/session-secret").read_text().strip() == secret
            assert (books / "book.txt").read_text() == "book"
            assert not (storage / "update-tmp/installation-incomplete").exists()
            verify = """import json,urllib.request,sqlite3,os
from pathlib import Path
assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version'] == TARGET
with sqlite3.connect('/app/storage/database/shuku.sqlite3') as db:
    assert db.execute('select position from ReaderResourceProgress where id=?', ('acceptance-progress',)).fetchone()[0] == '42'
    assert db.execute('select value from SystemSetting where key=?', ('acceptance-preserved',)).fetchone()[0] == 'configuration'
    assert db.execute('select version_num from alembic_version').fetchone()[0] == 'acceptance_b'
    db.execute('select * from AcceptanceMigration').fetchall()
pid=int(Path('/app/storage/update-tmp/worker-ready').read_text())
assert b'app.worker.main' in Path(f'/proc/{pid}/cmdline').read_bytes()
assert Path('/proc/1/cmdline').read_bytes().find(b'container-entry.py') >= 0
print('actual B API, migrated DB, progress, configuration, Worker and PID 1 verified')
""".replace("TARGET", repr(target))
            docker("exec", name, "python", "-c", verify)
            assert (
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    f'import pathlib;assert not any(pathlib.Path(f"/proc/{{p}}").exists() for p in {old_pids!r})',
                )
                == ""
            )
            backup = storage / "update-tmp/database-before-update.sqlite3"
            assert backup.is_file() and backup.stat().st_size > 0
            with sqlite3.connect(backup) as snapshot:
                assert (
                    snapshot.execute(
                        "select position from ReaderResourceProgress where id=?",
                        ("acceptance-progress",),
                    ).fetchone()[0]
                    == "42"
                )
                assert (
                    snapshot.execute(
                        "select version_num from alembic_version"
                    ).fetchone()[0]
                    != "acceptance_b"
                )
            for offline in (False, True):
                if offline:
                    docker("network", "disconnect", "bridge", name)
                docker("stop", "-t", "120", name)
                assert docker("inspect", "-f", "{{.State.ExitCode}}", name) == "143"
                docker("start", name)

                def ready_after_restart():
                    try:
                        docker("exec", name, "python", "-c", verify)
                        return True
                    except subprocess.CalledProcessError:
                        return False

                wait_for(ready_after_restart)
                assert docker("inspect", "-f", "{{.Id}}", name) == container
                assert docker("inspect", "-f", "{{.Image}}", name) == image
            print(
                json.dumps(
                    {
                        "container": container,
                        "image": image,
                        "A": seed_version,
                        "B": target,
                        "backup_sha256": hashlib.sha256(
                            backup.read_bytes()
                        ).hexdigest(),
                        "result": "passed: real prepare/install, migration, persistence, normal and offline restart",
                    }
                )
            )
        finally:
            logs = docker("logs", name)
            Path("/tmp/shuku-container-update-acceptance.log").write_text(logs)
            docker("rm", "-f", name)
            docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
