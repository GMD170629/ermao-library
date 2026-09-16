#!/usr/bin/env python3
"""Explicit real-image D1 acceptance, isolated Docker volume; no default test collection."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    name = "shuku-d1-" + uuid.uuid4().hex[:10]
    volume = name + "-data"
    books = name + "-books"
    docker("volume", "create", volume)
    docker("volume", "create", books)
    running = False

    def execute(code: str, python: str = "/usr/local/bin/python3.11") -> str:
        return docker("exec", name, python, "-c", code)

    def start(*, without_seed: bool = False) -> None:
        nonlocal running
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--user",
            "12345:12345",
            "-v",
            volume + ":/app/storage",
            "-v",
            books + ":/books:ro",
            *(
                [
                    "-e",
                    "SHUKU_IMAGE_ROOT=/absent",
                    "-e",
                    "SHUKU_DEPENDENCY_SEED=/absent",
                ]
                if without_seed
                else []
            ),
            args.image,
        )
        running = True
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "/usr/local/bin/python3.11",
                    "-c",
                    "import urllib.request; from pathlib import Path; assert Path('/app/storage/update-tmp/worker-ready').exists(); assert Path('/books/sentinel').read_text()=='original-book'; assert urllib.request.urlopen('http://127.0.0.1:3000/login').status == 200; assert urllib.request.urlopen('http://127.0.0.1:3000/api/health').status == 200",
                ],
                capture_output=True,
                check=False,
            )
            if probe.returncode == 0:
                return
            if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                raise RuntimeError(docker("logs", name))
            time.sleep(1)
        raise RuntimeError(docker("logs", name))

    def stop() -> None:
        nonlocal running
        docker("stop", "-t", "30", name)
        assert docker("inspect", "-f", "{{.State.ExitCode}}", name) == "143"
        docker("rm", name)
        running = False

    def offline_command(code: str) -> str:
        return docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "12345:12345",
            "-v",
            volume + ":/app/storage",
            "--entrypoint",
            "/usr/local/bin/python3.11",
            args.image,
            "-c",
            code,
        )

    try:
        docker(
            "run",
            "--rm",
            "-v",
            volume + ":/app/storage",
            "-v",
            books + ":/books",
            "--entrypoint",
            "sh",
            args.image,
            "-c",
            "chown 12345:12345 /app/storage && touch /app/storage/.acceptance-volume && printf original-book > /books/sentinel",
        )
        start()
        assert execute(
            "import importlib.util; assert importlib.util.find_spec('fastapi') is None; print('fixed environment has no business dependencies')"
        )
        business = "/app/storage/dependencies/python/bin/python"
        print(
            execute(
                "import sys,site,fastapi; assert sys.prefix=='/app/storage/dependencies/python'; assert not site.ENABLE_USER_SITE; assert all('/usr/local/lib/python3.11/site-packages' != p for p in sys.path); print('business environment isolated')",
                business,
            )
        )
        processes = json.loads(
            execute(
                "import json; from pathlib import Path; print(json.dumps([p.read_bytes().replace(b'\\0',b' ').decode() for p in Path('/proc').glob('[0-9]*/cmdline') if p.is_file()]))"
            )
        )
        for role in ("-m uvicorn app.main:app", "-m app.worker.main"):
            assert any(
                command.startswith(business + " ") and role in command
                for command in processes
            )
        assert "prestart outcome=success" in docker("logs", name)
        assert execute(
            "from pathlib import Path; import json; s=Path('/app/storage'); (s/'covers/sentinel').write_text('keep'); (s/'configuration').write_text('keep'); print(json.loads((s/'dependencies/installed.json').read_text())['identity'])"
        )
        execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); c.execute('PRAGMA user_version=321'); c.close()"
        )
        snapshot = execute(
            "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'dependencies/installed.json',s/'dependencies/python/pyvenv.cfg',s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
        )
        # A competing conversion must fail while the launcher lock is held.
        blocked = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "/usr/local/bin/python3.11",
                "/opt/shuku-launcher/container-entry.py",
                "--convert-legacy",
            ],
            capture_output=True,
            check=False,
        )
        assert blocked.returncode != 0 and b"already running" in blocked.stderr
        stop()
        start(without_seed=True)
        assert snapshot == execute(
            "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'dependencies/installed.json',s/'dependencies/python/pyvenv.cfg',s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
        )
        assert execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); assert c.execute('PRAGMA user_version').fetchone()==(321,); c.close(); print('database retained')"
        )
        stop()
        # Convert only this isolated deployment to a known v1-shaped fixture.
        offline_command(
            "from pathlib import Path; import json,shutil; s=Path('/app/storage'); p=s/'runtime/application.json'; v=json.loads(p.read_text()); v.pop('protocol'); p.write_text(json.dumps(v)); shutil.rmtree(s/'dependencies')"
        )
        refused = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "12345:12345",
                "-v",
                volume + ":/app/storage",
                args.image,
            ],
            capture_output=True,
            check=False,
        )
        assert refused.returncode != 0 and b"--convert-legacy" in refused.stderr
        print(
            docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "12345:12345",
                "-v",
                volume + ":/app/storage",
                "--entrypoint",
                "/usr/local/bin/python3.11",
                args.image,
                "/opt/shuku-launcher/container-entry.py",
                "--convert-legacy",
            )
        )
        start()
        assert execute(
            "from pathlib import Path; s=Path('/app/storage'); assert (s/'update-tmp/database-before-dependency-conversion.sqlite3').is_file(); assert (s/'covers/sentinel').read_text()=='keep'; print('conversion preserved data')"
        )
        preserved = json.loads(
            execute(
                "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
            )
        )
        assert all(
            json.loads(snapshot)[key] == value for key, value in preserved.items()
        )
        assert execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); assert c.execute('PRAGMA user_version').fetchone()==(321,); c.close(); print('converted database retained')"
        )
        stop()
        # A newer/unknown database must not be made acceptable by conversion.
        offline_command(
            "from pathlib import Path; import json,shutil,sqlite3; s=Path('/app/storage'); p=s/'runtime/application.json'; v=json.loads(p.read_text()); v.pop('protocol'); p.write_text(json.dumps(v)); shutil.rmtree(s/'dependencies'); c=sqlite3.connect(s/'database/shuku.sqlite3'); c.execute(\"UPDATE alembic_version SET version_num='future_schema'\"); c.commit(); c.close()"
        )
        rejected = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "12345:12345",
                "-v",
                volume + ":/app/storage",
                "--entrypoint",
                "/usr/local/bin/python3.11",
                args.image,
                "/opt/shuku-launcher/container-entry.py",
                "--convert-legacy",
            ],
            capture_output=True,
            check=False,
        )
        assert rejected.returncode != 0
        assert offline_command(
            "from pathlib import Path; import json,sqlite3; s=Path('/app/storage'); assert 'protocol' not in json.loads((s/'runtime/application.json').read_text()); c=sqlite3.connect(s/'database/shuku.sqlite3'); assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('future_schema',); c.close(); print('unknown schema rejected without downgrade')"
        )
        print(
            "PASS: API, Worker, schema, Web; non-root; offline initialization/restart; v1 refusal, locked conversion, unknown-schema refusal"
        )
    finally:
        if running:
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )
        docker("volume", "rm", volume, books)


if __name__ == "__main__":
    main()
