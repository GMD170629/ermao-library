"""Exact candidate acceptance behind accept_container_update.py; disposable volumes only."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from container_update_source import AcceptanceSource

ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str) -> str:
    return subprocess.check_output(
        ["docker", *args],
        text=True,
        stderr=subprocess.STDOUT if args[0] == "logs" else subprocess.PIPE,
    ).strip()


def wait(check, seconds=300):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise AssertionError("Candidate acceptance timed out")


def select_platforms(index: dict, image: str) -> list[tuple[str, str, str]]:
    result = []
    for architecture, platform in [
        ("amd64", "linux-x86_64"),
        ("arm64", "linux-aarch64"),
    ]:
        matches = [
            m
            for m in index.get("manifests", [])
            if m.get("platform", {}).get("architecture") == architecture
            and m.get("platform", {}).get("os") == "linux"
            and m.get("annotations", {}).get("vnd.docker.reference.type")
            != "attestation-manifest"
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one runtime manifest for {architecture}"
            )
        digest = matches[0]["digest"]
        import re

        if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("Invalid runtime digest")
        result.append((architecture, platform, image.split("@")[0] + "@" + digest))
    return result


def accept_candidates(args) -> None:
    report = {"image": args.image, "results": []}
    try:
        if args.both_architectures:
            platforms = select_platforms(
                json.loads(
                    docker("buildx", "imagetools", "inspect", args.image, "--raw")
                ),
                args.image,
            )
        else:
            info = json.loads(docker("image", "inspect", args.image))[0]
            arch = info["Architecture"]
            platforms = [
                (
                    arch,
                    {"amd64": "linux-x86_64", "arm64": "linux-aarch64"}[arch],
                    args.image,
                )
            ]
        for architecture, platform, image in platforms:
            if args.both_architectures:
                docker("pull", "--platform", f"linux/{architecture}", image)
            # Always test a direct jump. Additionally exercise previous quick -> candidate.
            paths = [[args.candidate_packages]]
            if args.prior_packages:
                paths.append([args.prior_packages, args.candidate_packages])
            for sequence in paths:
                result = accept_sequence(
                    image, architecture, platform, sequence, args.browser
                )
                report["results"].append(result)
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")


def accept_sequence(
    image: str, architecture: str, platform: str, sequence: list[Path], browser: bool
) -> dict:
    name = "shuku-candidate-" + uuid.uuid4().hex[:10]
    volume = name + "-storage"
    docker("volume", "create", volume)
    with tempfile.TemporaryDirectory(prefix=name) as temporary:
        root = Path(temporary)
        packages = root / "packages"
        packages.mkdir()
        books = root / "books"
        (books / "reader").mkdir(parents=True)
        (books / "book.txt").write_text("book")
        shutil.copyfile(
            ROOT / "test-data/library/epub/reader-v2.epub",
            books / "reader/reader-v2.epub",
        )
        original_books = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in books.rglob("*")
            if p.is_file()
        }
        injection = root / "injection"
        injection.mkdir()
        sentinel = root / "acceptance-only"
        sentinel.touch()
        source = AcceptanceSource(packages)
        source.injection(injection)
        source.release_download.set()
        container = None
        try:
            docker(
                "run",
                "--rm",
                "--pull=never",
                "--platform",
                f"linux/{architecture}",
                "--entrypoint",
                "sh",
                "-v",
                f"{volume}:/app/storage",
                image,
                "-c",
                "touch /app/storage/.acceptance-volume && chown 1000:1000 /app/storage /app/storage/.acceptance-volume",
            )
            container = docker(
                "run",
                "-d",
                "--pull=never",
                "--platform",
                f"linux/{architecture}",
                "--name",
                name,
                "--user",
                "1000:1000",
                "--add-host",
                "host.docker.internal:host-gateway",
                "-p",
                "127.0.0.1::3000",
                "-v",
                f"{volume}:/app/storage",
                "-v",
                f"{books}:/books",
                "-v",
                f"{ROOT}:/tooling:ro",
                "-v",
                f"{injection / 'sitecustomize.py'}:/usr/local/lib/python3.11/sitecustomize.py:ro",
                "-v",
                f"{sentinel}:/acceptance-only:ro",
                image,
            )
            base = (
                "http://127.0.0.1:" + docker("port", name, "3000/tcp").rsplit(":", 1)[1]
            )
            client = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )

            def request(path, payload=None):
                with client.open(
                    urllib.request.Request(
                        base + path,
                        data=json.dumps(payload).encode()
                        if payload is not None
                        else None,
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=15,
                ) as response:
                    return json.load(response)

            def exec_python(code):
                return docker("exec", name, "python", "-c", code)

            def version():
                return exec_python(
                    "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version'])"
                )

            def healthy():
                if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                    raise RuntimeError("Candidate container exited before healthy")
                return request("/api/health")

            wait(healthy)
            request(
                "/api/auth/setup",
                {
                    "email": "acceptance@example.com",
                    "password": "Acceptance-password-42",
                    "name": "Acceptance",
                },
            )
            docker(
                "exec",
                "-w",
                "/app/storage/runtime/apps/api-python",
                name,
                "/app/storage/dependencies/python/bin/python",
                "/tooling/scripts/container_update_fixture.py",
                "--build-only",
                "--seed-only",
            )
            current = version()
            versions = [current]
            updates = []
            image_id = docker("inspect", "-f", "{{.Image}}", name)
            secret = exec_python(
                "from pathlib import Path;import hashlib;print(hashlib.sha256(Path('/app/storage/secrets/session-secret').read_bytes()).hexdigest())"
            )
            original_schema = exec_python(
                "import urllib.request,json;v=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'));v['info'].pop('version');print(json.dumps(v,sort_keys=True))"
            )
            snapshot = """from pathlib import Path
import json,hashlib,os
s=Path('/app/storage'); record=json.loads((s/'dependencies/installed.json').read_text()); paths=[]
for package in record['packages']:
    if package['ecosystem']=='node': paths.extend(s/'runtime'/f for f in package['files'])
for package in record['python_records']: paths.extend(s/'dependencies/python'/f['path'] for f in package['files'])
print(json.dumps({str(p):[os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest(),p.lstat().st_ino,p.lstat().st_mtime_ns] for p in paths},sort_keys=True))
"""
            before_dependencies = exec_python(snapshot)
            schema_snapshot = "import sqlite3,json;db=sqlite3.connect('/app/storage/database/shuku.sqlite3');print(json.dumps([db.execute('select name,sql from sqlite_master order by name').fetchall(),db.execute('select version_num from alembic_version').fetchall()]))"
            original_database_schema = exec_python(schema_snapshot)

            def browser_step(action, target):
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
                        current,
                        target,
                        str(root / "browser-profile"),
                    ],
                    cwd=ROOT,
                    check=True,
                    timeout=180,
                )

            for directory in sequence:
                references = list(
                    directory.resolve().glob(
                        f"shuku-*-{platform}-v2.json.reference.json"
                    )
                )
                if len(references) != 1:
                    raise ValueError(
                        "Expected exactly one candidate reference per platform"
                    )
                reference = json.loads(references[0].read_text())
                target = reference["version"]
                if tuple(map(int, target.split("."))) <= tuple(
                    map(int, current.split("."))
                ):
                    raise ValueError(
                        "Candidate must upgrade the actual current version"
                    )
                for path in directory.resolve().iterdir():
                    if path.is_file():
                        shutil.copyfile(path, packages / path.name)
                (packages / "index.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "repository": "GMD170629/ermao-library",
                            "releases": [
                                {
                                    "version": target,
                                    "tag": "v" + target,
                                    "notesPath": f"v{target}.md",
                                    "publishedAt": "2026-09-20T00:00:00Z",
                                    "releaseUrl": f"https://github.com/GMD170629/ermao-library/releases/tag/v{target}",
                                    "dependencyReleases": [reference],
                                }
                            ],
                        }
                    )
                )
                notes = ROOT / "release-notes" / f"v{target}.md"
                (packages / f"v{target}.md").write_text(
                    notes.read_text()
                    if notes.exists()
                    else f"# v{target}\n\n## zh-CN\n候选更新验收\n\n## en-US\nCandidate acceptance\n"
                )
                available = request("/api/updates/check")["data"]["releases"]
                assert (
                    available
                    and available[0]["version"] == target
                    and available[0]["installable"]
                ), available
                if browser:
                    if len(versions) == 1:
                        browser_step("read", target)
                    browser_step("download", target)
                else:
                    request("/api/updates/prepare", {"version": target})

                def ready():
                    state = request("/api/updates/status")["data"]
                    if state["phase"] == "failed":
                        raise RuntimeError("Preparation failed: " + json.dumps(state))
                    return state["phase"] == "ready"

                wait(ready)
                assert exec_python(snapshot) == before_dependencies, (
                    "Preparation changed dependencies"
                )
                assert version() == current, (
                    "Preparation installed without confirmation"
                )
                prepared = request("/api/updates/status")["data"]
                if browser:
                    browser_step("cancel", target)
                    assert version() == current
                    browser_step("install", target)
                else:
                    request(
                        "/api/updates/install",
                        {
                            "version": target,
                            "sha256": reference["sha256"],
                            "plan_sha256": prepared["summary"]["plan_sha256"],
                        },
                    )

                def installed():
                    state = json.loads(
                        docker(
                            "exec",
                            name,
                            "cat",
                            "/app/storage/update-tmp/preparation.json",
                        )
                    )
                    if state["phase"] == "failed":
                        raise RuntimeError("Installation failed: " + json.dumps(state))
                    return state["phase"] == "success"

                wait(installed)
                wait(lambda target=target: version() == target)
                assert exec_python(snapshot) == before_dependencies, (
                    "code-only changed dependency files"
                )
                assert exec_python(schema_snapshot) == original_database_schema, (
                    "code-only changed database schema"
                )
                updates.append(
                    {
                        "version": target,
                        "manifestSha256": reference["sha256"],
                        "summary": prepared["summary"],
                    }
                )
                after_schema = exec_python(
                    "import urllib.request,json;v=json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'));v['info'].pop('version');print(json.dumps(v,sort_keys=True))"
                )
                assert original_schema == after_schema, (
                    "code-only changed the runtime OpenAPI contract"
                )
                assert (
                    request("/api/auth/me")["data"]["user"]["email"]
                    == "acceptance@example.com"
                )
                if browser:
                    browser_step("verify", target)
                current = target
                versions.append(target)
            exec_python("""import sqlite3,json,urllib.request
from pathlib import Path
with sqlite3.connect('/app/storage/database/shuku.sqlite3') as db:
    assert db.execute('select position from ReaderResourceProgress where id=?',('acceptance-progress',)).fetchone()[0]=='42'
    assert db.execute('select value from SystemSetting where key=?',('acceptance-preserved',)).fetchone()[0]=='configuration'
r=json.loads(Path('/app/storage/update-tmp/worker-ready').read_text()); pid=r['pid']; assert Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19] == r['startTime']
assert not Path('/app/storage/update-tmp/installation-incomplete').exists()
assert urllib.request.urlopen('http://127.0.0.1:3000/').status==200
""")
            assert secret == exec_python(
                "from pathlib import Path;import hashlib;print(hashlib.sha256(Path('/app/storage/secrets/session-secret').read_bytes()).hexdigest())"
            )
            for offline in (False, True):
                docker("stop", "-t", "120", name)
                if offline:
                    docker("network", "disconnect", "bridge", name)
                docker("start", name)
                # API becomes ready before Web/Worker; wait for the entire startup barrier.
                restart_probe = """import urllib.request,json
from pathlib import Path
assert all(urllib.request.urlopen('http://127.0.0.1:3000'+p,timeout=10).status==200 for p in ['/','/api/health'])
r=json.loads(Path('/app/storage/update-tmp/worker-ready').read_text()); pid=r['pid']
assert Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19] == r['startTime']
"""
                wait(
                    lambda probe=restart_probe: (
                        version() == current and exec_python(probe) == ""
                    )
                )
                assert docker("inspect", "-f", "{{.Id}}", name) == container
                assert docker("inspect", "-f", "{{.Image}}", name) == image_id
            assert original_books == {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in books.rglob("*")
                if p.is_file()
            }
            return {
                "platform": platform,
                "versions": versions,
                "updates": updates,
                "imageId": image_id,
                "containerId": container,
                "browser": browser,
                "ordinaryAndOfflineRestart": True,
            }
        finally:
            if container:
                logs = docker("logs", name)
                print(logs[-12000:])
                subprocess.run(["docker", "rm", "-f", name], check=False)
            source.close()
            subprocess.run(["docker", "volume", "rm", volume], check=False)
