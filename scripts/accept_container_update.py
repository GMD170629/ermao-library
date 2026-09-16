#!/usr/bin/env python3
"""Explicit A -> B smoke against a prebuilt image, using disposable Docker data."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import shutil
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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Exercise separate download/install confirmations through real Web UI",
    )
    parser.add_argument(
        "--web-image",
        help="Prebuilt Dockerfile builder stage for isolated version B (required with --browser)",
    )
    args = parser.parse_args()
    if args.browser and not args.web_image:
        parser.error("--browser requires a real B Web builder image via --web-image")
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
        reader_book = books / "reader/reader-v2.epub"
        reader_book.parent.mkdir()
        shutil.copyfile(ROOT / "test-data/library/epub/reader-v2.epub", reader_book)
        reader_hash = hashlib.sha256(reader_book.read_bytes()).hexdigest()
        sentinel = root / "acceptance-only"
        sentinel.touch()
        source = None
        extra = []
        if args.browser:
            web = root / "web-b"
            web.mkdir()
            build_container = docker("create", "--pull=never", args.web_image)
            try:
                docker(
                    "cp",
                    build_container + ":/app/apps/web/.next/standalone",
                    str(web / "standalone"),
                )
                docker(
                    "cp",
                    build_container + ":/app/apps/web/.next/static",
                    str(web / "static"),
                )
                docker(
                    "cp", build_container + ":/app/apps/web/public", str(web / "public")
                )
            finally:
                docker("rm", build_container)
            from container_update_source import AcceptanceSource

            output = root / "packages"
            output.mkdir()
            injection = root / "injection"
            injection.mkdir()
            source = AcceptanceSource(output)
            source.injection(injection)
            extra = [
                "-v",
                f"{injection}:/acceptance-python:ro",
                "-e",
                "PYTHONPATH=/acceptance-python",
                "-v",
                f"{web}:/acceptance-web:ro",
            ]
        # Only the disposable Linux test volume is chowned, never the user library.
        docker(
            "run",
            "--rm",
            "--pull=never",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "-v",
            f"{volume}:/app/storage",
            args.image,
            "-c",
            "touch /app/storage/.acceptance-volume && chown 1000:1000 /app/storage /app/storage/.acceptance-volume",
        )
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
            "--user",
            "1000:1000",
            *extra,
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
                if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                    raise RuntimeError(
                        "acceptance container exited before becoming healthy"
                    )
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
                *(["--build-only"] if args.browser else []),
            )
            identity = json.loads(fixture.splitlines()[-1])
            target = identity["target"]
            if source is not None:
                docker("cp", name + ":/tmp/update-fixture/output/.", str(output))
                (output / f"v{target}.md").write_text(
                    "<!-- shuku:locale=zh-CN:start -->\n隔离验收更新\n<!-- shuku:locale=zh-CN:end -->\n<!-- shuku:locale=en-US:start -->\nIsolated acceptance update\n<!-- shuku:locale=en-US:end -->"
                )

                def browser(action):
                    subprocess.run(
                        [
                            "pnpm",
                            "--filter",
                            "@shuku/web",
                            "exec",
                            "tsx",
                            str(ROOT / "scripts/container_update_browser.mjs"),
                            base,
                            source.url,
                            action,
                            seed_version,
                            target,
                            str(root / "browser-profile"),
                        ],
                        check=True,
                        timeout=120,
                    )

                browser("read")
                browser("download")
                with request("/api/updates/status") as response:
                    assert json.load(response)["data"]["phase"] == "downloading"
                source.release_download.set()

                def prepared():
                    with request("/api/updates/status") as response:
                        state = json.load(response)["data"]
                        assert state["phase"] != "failed", state
                        return state["phase"] == "ready"

                wait_for(prepared)
                browser("cancel")
                with request("/api/updates/runtime") as response:
                    assert (
                        json.load(response)["data"]["current_version"] == seed_version
                    )
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "from pathlib import Path;assert not Path('/app/storage/update-tmp/install-request.json').exists()",
                )
                # Same running business PIDs prove preparation/cancellation did not restart.
                docker(
                    "exec",
                    name,
                    "python",
                    "-c",
                    f"from pathlib import Path;assert all(Path(f'/proc/{{p}}').exists() for p in {old_pids!r})",
                )
                browser("install")
            else:
                with request(
                    "/api/updates/install",
                    {"version": target, "sha256": identity["sha256"]},
                ) as response:
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
            if source is not None:
                browser("verify")
            docker("cp", name + ":/app/storage/.", str(storage))
            with request("/api/health") as response:
                assert response.headers["X-Acceptance-Code"] == "B"
            assert docker("inspect", "-f", "{{.Id}}", name) == container
            assert docker("inspect", "-f", "{{.Image}}", name) == image
            assert not (storage / "runtime/obsolete-acceptance-file").exists()
            assert (storage / "runtime/.initialized").read_text() == "1\n"
            assert (storage / "secrets/session-secret").read_text().strip() == secret
            assert (books / "book.txt").read_text() == "book"
            assert hashlib.sha256(reader_book.read_bytes()).hexdigest() == reader_hash
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
                        "uid_gid": docker("exec", name, "id"),
                        "browser": args.browser,
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
            if source is not None:
                source.close()
            logs = docker("logs", name)
            Path("/tmp/shuku-container-update-acceptance.log").write_text(logs)
            docker("rm", "-f", name)
            docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
