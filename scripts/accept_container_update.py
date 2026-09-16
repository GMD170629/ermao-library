#!/usr/bin/env python3
"""Explicit A -> B smoke against a prebuilt image, using disposable Docker data."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import urllib.response
import uuid
from email.message import Message
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
    parser.add_argument(
        "--dependencies",
        action="store_true",
        help="Explicit D3 real dependency update via administrator API",
    )
    args = parser.parse_args()
    if args.browser and not args.web_image:
        parser.error("--browser requires a real B Web builder image via --web-image")
    image_id = docker("images", "--quiet", args.image)
    if not image_id:
        raise RuntimeError("prebuilt local image required")
    docker("image", "inspect", image_id)
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
        if args.dependencies:
            from container_update_source import AcceptanceSource

            if source is None:
                output = root / "packages"
                output.mkdir()
                source = AcceptanceSource(output)
            context = root / "image-context"
            context.mkdir()
            shutil.copytree(
                ROOT / "apps/api-python/app",
                context / "app",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            shutil.copytree(
                ROOT / "apps/api-python/shuku_dependencies",
                context / "shuku_dependencies",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            source.inject_module(context / "app/bootstrap/updates.py")
            for filename in (
                "container-entry.py",
                "container_install.py",
                "dependency_install.py",
                "dependency_environment.py",
                "dependency_packages.py",
                "dependency_records.py",
                "dependency_update_fixture.py",
            ):
                shutil.copyfile(ROOT / "scripts" / filename, context / filename)
            web_copy = ""
            if args.browser:
                shutil.copytree(web, context / "web", symlinks=True)
                web_copy = "RUN rm -rf /opt/shuku-image/apps/web /opt/shuku-image/node_modules\nCOPY web/standalone /opt/shuku-image/\nCOPY web/static /opt/shuku-image/apps/web/.next/static\nCOPY web/public /opt/shuku-image/apps/web/public\n"
            (context / "Dockerfile").write_text(f"""FROM {args.image}
USER root
{web_copy}COPY app /opt/shuku-image/apps/api-python/app
COPY shuku_dependencies /opt/shuku-image/apps/api-python/shuku_dependencies
COPY shuku_dependencies /opt/shuku-launcher/shuku_dependencies
COPY container-entry.py container_install.py dependency_install.py dependency_environment.py dependency_packages.py dependency_records.py /opt/shuku-launcher/
COPY dependency_update_fixture.py /opt/dependency_update_fixture.py
RUN /usr/local/bin/python3.11 /opt/dependency_update_fixture.py
""")
            derived = name + "-image"
            docker("build", "--network=none", "-t", derived, str(context))
            args.image = derived
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

            offline_api = False

            def request(path, payload=None):
                if offline_api:
                    code = f"import urllib.request,json; r=urllib.request.Request('http://127.0.0.1:3000'+{path!r},data=(json.dumps({payload!r}).encode() if {payload is not None!r} else None),headers={{'Content-Type':'application/json','Cookie':{cookies!r}}}); s=urllib.request.urlopen(r,timeout=30); print(json.dumps({{'body':s.read().hex(),'status':s.status,'headers':dict(s.headers)}}))"
                    result = json.loads(docker("exec", name, "python", "-c", code))
                    headers = Message()
                    for key, value in result["headers"].items():
                        headers[key] = value
                    return urllib.response.addinfourl(
                        io.BytesIO(bytes.fromhex(result["body"])),
                        headers,
                        base + path,
                        result["status"],
                    )
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

            def restore_network():
                nonlocal base, offline_api
                docker("network", "connect", "bridge", name)
                # Docker Desktop drops published ports on network detach. A normal
                # restart restores them without changing the container or image.
                docker("stop", "-t", "120", name)
                assert docker("inspect", "-f", "{{.State.ExitCode}}", name) == "143"
                docker("start", name)
                base = (
                    "http://127.0.0.1:"
                    + docker("port", name, "3000/tcp").rsplit(":", 1)[1]
                )
                offline_api = False
                wait_for(healthy)

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
            initial_version = seed_version
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
                "/app/storage/dependencies/python/bin/python",
                "/tooling/scripts/container_update_fixture.py",
                *(["--build-only"] if args.browser or args.dependencies else []),
                *(["--dependencies"] if args.dependencies else []),
                *(["--two-updates"] if args.browser and args.dependencies else []),
            )
            identity = json.loads(fixture.splitlines()[-1])
            target = identity["target"]
            keep_code = """from pathlib import Path
import hashlib,json
s=Path('/app/storage'); record=json.loads((s/'dependencies/installed.json').read_text()); result={}
plan=json.loads((s/'update-tmp/prepared/plan.json').read_text()); keep=set(plan['difference']['keep'])
for p in record['packages']:
    if p['ecosystem']=='node' and 'node:'+p['location'] in keep:
        for name in p['files']:
            f=s/'runtime'/name
            if not f.is_symlink(): result[str(f)]=[hashlib.sha256(f.read_bytes()).hexdigest(),f.stat().st_ino,f.stat().st_mtime_ns]
for record in record['python_records']:
    if 'python:'+record['name'] in keep:
        for f in record['files']:
            p=s/'dependencies/python'/f['path']; result[str(p)]=[hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_ino,p.stat().st_mtime_ns]
Path('/tmp/d3-kept.json').write_text(json.dumps(result,sort_keys=True)); print(len(result))
"""
            cookies = "; ".join(
                f"{c.name}={c.value}"
                for handler in client.handlers
                if isinstance(handler, urllib.request.HTTPCookieProcessor)
                for c in handler.cookiejar
            )
            if args.browser:
                docker("cp", name + ":/tmp/update-fixture/output/.", str(output))
                if args.dependencies:
                    next_output = root / "packages-c"
                    next_output.mkdir()
                    docker(
                        "cp", name + ":/tmp/update-fixture/output-c/.", str(next_output)
                    )
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

                def dependency_snapshot():
                    return docker(
                        "exec",
                        name,
                        "python",
                        "-c",
                        """from pathlib import Path
import json,hashlib,os
s=Path('/app/storage'); r=s/'dependencies/installed.json'; record=json.loads(r.read_text()); result=[r.read_text()]
paths=[s/'runtime'/f for p in record['packages'] if p['ecosystem']=='node' for f in p['files']]
paths += [s/'dependencies/python'/f['path'] for p in record['python_records'] for f in p['files']]
for p in sorted(set(paths)):
    result.append([str(p),os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest(),p.lstat().st_ino,p.lstat().st_mtime_ns])
print(hashlib.sha256(json.dumps(result).encode()).hexdigest())
""",
                    )

                browser("read")
                before_preparation = (
                    dependency_snapshot() if args.dependencies else None
                )
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
                if args.dependencies:
                    assert dependency_snapshot() == before_preparation
                    print(
                        "Preparation/cancellation retained all dependency files and installed records:",
                        before_preparation,
                        flush=True,
                    )
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
                if args.dependencies:
                    docker("exec", name, "python", "-c", keep_code)
                    docker(
                        "exec",
                        "--user",
                        "0:0",
                        name,
                        "sh",
                        "-c",
                        "rm -rf /opt/shuku-dependency-seed/wheels /tmp/update-fixture/dependency-seed /tmp/update-fixture/output /tmp/update-fixture/output-c /root/.cache/uv",
                    )
                    # Pause only PID 1 while the live API accepts the confirmation.
                    # Resume it after browser exit and network removal: all installation is offline.
                    docker("kill", "--signal=STOP", name)
                browser("install")
                if args.dependencies:
                    docker("network", "disconnect", "bridge", name)
                    offline_api = True
                    docker("kill", "--signal=CONT", name)
            elif args.dependencies:
                docker("cp", name + ":/tmp/update-fixture/output/.", str(output))
                source.release_download.set()
                with request("/api/updates/prepare", {"version": target}) as response:
                    assert response.status == 202

                def dependency_ready():
                    with request("/api/updates/status") as response:
                        state = json.load(response)["data"]
                    assert state["phase"] != "failed", state
                    return state["phase"] == "ready"

                wait_for(dependency_ready, 300)
                with request("/api/updates/status") as response:
                    ready = json.load(response)["data"]
                docker("exec", name, "python", "-c", keep_code)
                # Remove all original wheels/cache; no implicit full installation is possible.
                docker(
                    "exec",
                    "--user",
                    "0:0",
                    name,
                    "sh",
                    "-c",
                    "rm -rf /opt/shuku-dependency-seed/wheels /tmp/update-fixture/dependency-seed /tmp/update-fixture/output /root/.cache/uv",
                )
                cookies = "; ".join(
                    f"{c.name}={c.value}"
                    for handler in client.handlers
                    if isinstance(handler, urllib.request.HTTPCookieProcessor)
                    for c in handler.cookiejar
                )
                docker("network", "disconnect", "bridge", name)
                offline_api = True
                payload = {
                    "version": target,
                    "sha256": identity["sha256"],
                    "plan_sha256": ready["summary"]["plan_sha256"],
                }
                code = f"import urllib.request,json; r=urllib.request.Request('http://127.0.0.1:3000/api/updates/install',data=json.dumps({payload!r}).encode(),headers={{'Content-Type':'application/json','Cookie':{cookies!r}}}); print(urllib.request.urlopen(r,timeout=60).status)"
                assert docker("exec", name, "python", "-c", code) == "202"
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
            if args.dependencies:
                # Compare exactly the pre-update keep files (the final set also contains E).
                check = "import json,hashlib; from pathlib import Path; old=json.loads(Path('/tmp/d3-kept.json').read_text()); assert all([hashlib.sha256(Path(p).read_bytes()).hexdigest(),Path(p).stat().st_ino,Path(p).stat().st_mtime_ns]==v for p,v in old.items()); print(len(old))"
                kept_count = docker("exec", name, "python", "-c", check)
                print("D3 kept files with identical digest/inode/mtime:", kept_count)
                print(
                    docker(
                        "exec", name, "cat", "/app/storage/update-tmp/installation.log"
                    )
                )
                restore_network()
                print(
                    "HTTP evidence first update:",
                    json.dumps(dict(source.requests)),
                    json.dumps(dict(source.bytes)),
                )
            if args.browser:
                browser("verify")
            docker("cp", name + ":/app/storage/.", str(storage))
            with request("/api/health") as response:
                assert response.headers["X-Acceptance-Code"] == "B"
                if args.dependencies:
                    assert response.headers["X-Acceptance-Dependency"] == "2"
                if args.dependencies:
                    assert response.headers["X-Acceptance-Dependency"] == "2"
            if args.dependencies:
                with request("/api/auth/me") as response:
                    assert (
                        json.load(response)["data"]["user"]["email"]
                        == "acceptance@example.com"
                    )
                with request(
                    "/api/reader/v5/resources/acceptance-resource/bootstrap"
                ) as response:
                    assert response.status == 200
                with request(
                    "/api/reader/v5/resources/acceptance-resource/publication"
                ) as response:
                    assert response.read() == b"book"
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
            if args.browser and args.dependencies:
                first_target = target
                seed_version = first_target
                source.root = next_output
                source.requests.clear()
                source.bytes.clear()
                target = json.loads((next_output / "index.json").read_text())[
                    "releases"
                ][0]["version"]
                (next_output / f"v{target}.md").write_text(
                    (output / f"v{first_target}.md").read_text()
                )
                # No keep artifacts exist in the second download source either.
                for artifact in next_output.iterdir():
                    if artifact.suffix in (".whl", ".tar"):
                        artifact.unlink()
                source.release_download.clear()
                before_preparation = dependency_snapshot()
                browser("download")
                source.release_download.set()
                wait_for(prepared)
                with request("/api/updates/status") as response:
                    second = json.load(response)["data"]
                assert second["summary"]["dependency_bytes"] == 0
                assert second["summary"]["install"] == second["summary"]["remove"] == 0
                docker("exec", name, "python", "-c", keep_code)
                browser("cancel")
                assert dependency_snapshot() == before_preparation
                docker("kill", "--signal=STOP", name)
                browser("install")
                docker("network", "disconnect", "bridge", name)
                offline_api = True
                docker("kill", "--signal=CONT", name)
                wait_for(installed, 300)
                kept_count = docker("exec", name, "python", "-c", check)
                second_log = docker(
                    "exec", name, "cat", "/app/storage/update-tmp/installation.log"
                )
                assert "dependency_operation=check packages=[]" in second_log
                assert "application_update phase=success" in second_log
                assert not any(
                    operation in second_log
                    for operation in (
                        "dependency_operation=install",
                        "dependency_operation=uninstall",
                        "dependency_operation=node_",
                    )
                )
                assert not any(
                    name.endswith((".whl", ".tar")) for name in source.requests
                )
                assert (
                    sum(
                        count
                        for name, count in source.requests.items()
                        if name.endswith("-code.tar.gz")
                    )
                    == 1
                )
                print(
                    "HTTP evidence second update:",
                    json.dumps(dict(source.requests)),
                    json.dumps(dict(source.bytes)),
                )
                print(
                    "Second update kept digest/inode/mtime:",
                    kept_count,
                    "dependency bytes: Python=0 Node=0; operations:",
                    second_log,
                )
                restore_network()
                browser("verify")
                with request("/api/health") as response:
                    assert response.headers["X-Acceptance-Code"] == "C"
                    assert response.headers["X-Acceptance-Dependency"] == "2"
                verify = verify.replace(repr(first_target), repr(target))
                assert (
                    docker(
                        "exec", name, "cat", "/app/storage/secrets/session-secret"
                    ).strip()
                    == secret
                )
                docker("exec", name, "python", "-c", verify)
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
                        "versions": [initial_version, seed_version, target]
                        if args.browser and args.dependencies
                        else [initial_version, target],
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
            if args.dependencies:
                docker("image", "rm", args.image)


if __name__ == "__main__":
    main()
