"""Real HTTP requests and small installed package fixtures; never builds Web."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import shutil
import sysconfig
import tarfile
import threading
import time
import urllib.request
import venv
import zipfile
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_preparation as legacy_tests

load_script = legacy_tests.load_script
program_package = legacy_tests.program_package

from app.modules.updates.application.dependency_release import DependencySet
from app.modules.updates.application.models import ReleaseReference, UpdateError
from app.modules.updates.application.preparation import UpdatePreparation
from app.modules.updates.infrastructure.dependency_preparation import verify_local
from app.modules.updates.infrastructure.official_source import (
    OfficialHTTP,
    OfficialRedirects,
    OfficialReleases,
)
from app.modules.updates.infrastructure.preparation_worker import PreparationWorker
from app.modules.updates.presentation.http import use_cases
from shuku_dependencies import canonical_digest, digest, generate, installed_records


def wheel(root: Path, version: str = "1.0", body: bytes = b"VALUE = 1\n") -> Path:
    directory = f"demo-{version}.dist-info"
    files = {
        "demo.py": body,
        f"{directory}/METADATA": f"Name: demo\nVersion: {version}\n".encode(),
        f"{directory}/WHEEL": b"Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = "".join(
        f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()},{len(content)}\n"
        for name, content in files.items()
    )
    files[f"{directory}/RECORD"] = (record + f"{directory}/RECORD,,\n").encode()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"demo-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def node(root: Path, name: str, version: str, location: str | None = None) -> None:
    path = root / (location or f"node_modules/{name}")
    path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text(json.dumps({"name": name, "version": version}))
    (path / "index.js").write_text("module.exports=" + json.dumps(version))


def snapshot(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): (
            str(p.readlink()) if p.is_symlink() else digest(p),
            p.lstat().st_mtime_ns,
            p.lstat().st_mode,
        )
        for p in root.rglob("*")
        if (p.is_file() or p.is_symlink()) and "update-tmp" not in p.parts
    }


@pytest.fixture()
def packages(tmp_path, program_package):
    image = tmp_path / "image"
    shutil.copytree(program_package[0], image, symlinks=True)
    (image / "apps/web/node_modules").unlink()
    shutil.rmtree(image / "node_modules")
    for name in ("a", "b", "c", "d"):
        node(image, name, "1")
    identity = json.loads((image / "application.json").read_text())
    identity["protocol"] = 2
    (image / "application.json").write_text(json.dumps(identity))
    seed = tmp_path / "seed"
    seed.mkdir()
    installed_wheel = wheel(seed / "wheels")
    initial = generate(image, seed)
    storage = tmp_path / "storage"
    storage.mkdir()
    shutil.copytree(image, storage / "runtime", symlinks=True)
    business = storage / "dependencies/python"
    venv.EnvBuilder(with_pip=False).create(business)
    site = next(business.glob("lib/python*/site-packages"))
    with zipfile.ZipFile(installed_wheel) as archive:
        archive.extractall(site)  # trusted fixture only
    (storage / "dependencies/installed.json").write_text(
        json.dumps({**initial, "python_records": installed_records(business)})
    )
    for name in (
        "database/shuku.sqlite3",
        "secrets/session-secret",
        "covers/book",
        "books/book",
        "configuration",
    ):
        path = storage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"protected")
    fixed = tmp_path / "environment.json"
    fixed.write_text(
        json.dumps(
            {
                "environment": identity["environment"],
                "inventory": {"abi": sysconfig.get_config_var("SOABI")},
            }
        )
    )
    result = SimpleNamespace(
        root=tmp_path,
        image=image,
        seed=seed,
        storage=storage,
        fixed=fixed,
        initial=initial,
    )

    def build():
        (seed / "manifest.json").write_text(json.dumps(generate(image, seed)))
        output = tmp_path / "output"
        output.mkdir(exist_ok=True)
        reference = ReleaseReference.model_validate(
            load_script("build-application-package").build_release(
                image, output, seed, fixed
            )
        )
        result.reference, result.output = reference, output
        return reference

    result.build = build
    yield result


@pytest.fixture()
def downloads(packages):
    requests, sizes = Counter(), Counter()
    hold, entered = threading.Event(), threading.Event()
    hold.set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.rsplit("/", 1)[-1]
            if name == "index.json":
                p = packages.reference
                content = json.dumps(
                    {
                        "schemaVersion": 1,
                        "repository": "GMD170629/ermao-library",
                        "releases": [
                            {
                                "version": p.version,
                                "tag": "v" + p.version,
                                "notesPath": "v" + p.version + ".md",
                                "publishedAt": "2026-09-16T00:00:00Z",
                                "releaseUrl": f"https://github.com/GMD170629/ermao-library/releases/tag/v{p.version}",
                                "appPackages": [],
                                "dependencyReleases": [p.model_dump()],
                            }
                        ],
                    }
                ).encode()
            else:
                requests[name] += 1
                entered.set()
                hold.wait(10)
                path = packages.output / name
                if not path.is_file():
                    self.send_error(404)
                    return
                content = path.read_bytes()
                sizes[name] += len(content)
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    class LocalHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(
                lambda host, **kwargs: http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, **kwargs
                ),
                request,
            )

    transport = OfficialHTTP(
        urllib.request.build_opener(
            urllib.request.ProxyHandler({}), OfficialRedirects(), LocalHTTPS()
        )
    )
    worker = PreparationWorker(
        packages.storage,
        transport,
        ReleaseReference.model_validate(
            {
                "version": "1.0.4",
                "environment": json.loads(packages.fixed.read_text())["environment"],
                "filename": "shuku-1.0.4-linux-x86_64-v2.json",
                "size": 1,
                "sha256": "a" * 64,
            }
        ).environment,
    )
    updates = UpdatePreparation(
        "1.0.0", worker.environment, OfficialReleases(transport, 2), worker, protocol=2
    )
    try:
        yield SimpleNamespace(
            requests=requests,
            sizes=sizes,
            worker=worker,
            updates=updates,
            hold=hold,
            entered=entered,
        )
    finally:
        hold.set()
        worker.close()
        server.shutdown()
        thread.join()
        server.server_close()


def finish(downloads):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = downloads.worker.status()
        if state.phase in ("ready", "failed"):
            return state
        time.sleep(0.01)
    raise AssertionError("preparation did not finish")


def change_target(packages):
    shutil.rmtree(packages.image / "node_modules/c")
    node(packages.image, "b", "2")
    node(packages.image, "e", "1")
    packages.build()


@pytest.mark.parametrize("current", ["1.0.0", "1.0.1", "1.0.3"])
def test_selective_http_downloads_and_unchanged_business(packages, downloads, current):
    downloads.updates.current = current
    identity_path = packages.storage / "runtime/application.json"
    identity = json.loads(identity_path.read_text())
    identity["version"] = current
    identity_path.write_text(json.dumps(identity))
    before = snapshot(packages.storage)
    change_target(packages)
    downloads.updates.prepare(True, "1.0.4")
    state = finish(downloads)
    assert state.phase == "ready", state
    manifest = json.loads((packages.output / packages.reference.filename).read_text())
    artifacts = {
        p["name"]: p["artifact"]["filename"]
        for p in manifest["dependencies"]["packages"]
    }
    assert set(downloads.requests) == {
        packages.reference.filename,
        manifest["code"]["filename"],
        artifacts["b"],
        artifacts["e"],
    }
    assert all(count == 1 for count in downloads.requests.values())
    assert (
        downloads.requests[artifacts["a"]]
        == downloads.requests[artifacts["d"]]
        == downloads.requests[artifacts["demo"]]
        == 0
    )
    assert (
        sum(downloads.sizes.values()) == state.downloaded == state.summary.total_bytes
    )
    assert (
        state.summary.dependency_bytes
        == downloads.sizes[artifacts["b"]] + downloads.sizes[artifacts["e"]]
    )
    plan = json.loads((packages.storage / "update-tmp/prepared/plan.json").read_text())
    assert plan["difference"] == {
        "keep": ["node:node_modules/a", "node:node_modules/d", "python:demo"],
        "install": ["node:node_modules/b", "node:node_modules/e"],
        "remove": ["node:node_modules/c"],
    }
    assert before == snapshot(packages.storage)
    assert not (packages.storage / "update-tmp/install-request.json").exists()
    with pytest.raises(UpdateError, match="PLAN_CHANGED"):
        downloads.updates.install(True, "1.0.4", packages.reference.sha256)
    with pytest.raises(UpdateError, match="PLAN_CHANGED"):
        downloads.worker.install(
            "1.0.4", packages.reference.sha256, packages.reference.environment, "1.0.0"
        )
    assert len(state.model_dump_json()) < 16384
    print("HTTP evidence:", dict(downloads.requests), "bytes:", dict(downloads.sizes))


@pytest.mark.parametrize("change", ["code", "remove", "same-version", "python-replace"])
def test_other_differences(packages, downloads, change):
    before = snapshot(packages.storage)
    if change == "code":
        (packages.image / "apps/web/server.js").write_text("// new code")
    elif change == "remove":
        shutil.rmtree(packages.image / "node_modules/c")
    elif change == "same-version":
        (packages.image / "node_modules/a/index.js").write_text(
            "// changed artifact, same version"
        )
    else:
        wheel(packages.seed / "wheels", body=b"VALUE = 2\n")
    packages.build()
    downloads.updates.prepare(True, "1.0.4")
    state = finish(downloads)
    assert state.phase == "ready", state
    assert state.summary.install == (
        1 if change in ("same-version", "python-replace") else 0
    )
    if change in ("code", "remove"):
        assert state.summary.dependency_bytes == 0
        assert len(downloads.requests) == 2
    else:
        assert len(downloads.requests) == 3
    assert snapshot(packages.storage) == before


@pytest.mark.parametrize(
    "damage", ["node", "record", "unknown-python", "unknown-node", "missing-python"]
)
def test_local_damage_cannot_be_keep(packages, downloads, damage):
    packages.build()
    if damage == "node":
        (packages.storage / "runtime/node_modules/a/index.js").write_text("damaged")
    elif damage == "record":
        path = packages.storage / "dependencies/installed.json"
        record = json.loads(path.read_text())
        record["python_records"][0]["files"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(record))
    elif damage == "unknown-python":
        site = next(
            (packages.storage / "dependencies/python").glob("lib/python*/site-packages")
        )
        (site / "rogue.py").write_text("unknown")
    elif damage == "missing-python":
        next(
            (packages.storage / "dependencies/python").glob(
                "lib/python*/site-packages/demo.py"
            )
        ).unlink()
    else:
        node(packages.storage / "runtime", "unknown", "1")
    before = snapshot(packages.storage)
    downloads.updates.prepare(True, "1.0.4")
    state = finish(downloads)
    assert state.phase == "failed"
    assert state.error in ("LOCAL_DEPENDENCIES_INVALID", "LOCAL_RECORDS_DRIFT")
    assert len(downloads.requests) == 1
    assert snapshot(packages.storage) == before


@pytest.mark.parametrize(
    "failure", ["missing", "corrupt", "platform", "space", "escape"]
)
def test_bad_target_never_writes_business(packages, downloads, monkeypatch, failure):
    change_target(packages)
    manifest_path = packages.output / packages.reference.filename
    manifest = json.loads(manifest_path.read_text())
    selected = next(p for p in manifest["dependencies"]["packages"] if p["name"] == "b")
    if failure == "missing":
        (packages.output / selected["artifact"]["filename"]).unlink()
    elif failure == "corrupt":
        path = packages.output / selected["artifact"]["filename"]
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    elif failure == "space":
        monkeypatch.setattr(
            "app.modules.updates.infrastructure.preparation_worker.check_space",
            lambda *a: (_ for _ in ()).throw(UpdateError("INSUFFICIENT_SPACE")),
        )
    else:
        if failure == "platform":
            manifest["python_abi"] = "wrong"
        else:
            selected["files"][0] = "../../escape"
            deps = manifest["dependencies"]
            deps["identity"] = canonical_digest(
                {k: v for k, v in deps.items() if k != "identity"}
            )
        manifest_path.write_text(json.dumps(manifest))
        packages.reference = packages.reference.model_copy(
            update={
                "size": manifest_path.stat().st_size,
                "sha256": digest(manifest_path),
            }
        )
    before = snapshot(packages.storage)
    downloads.updates.prepare(True, "1.0.4")
    state = finish(downloads)
    assert state.phase == "failed"
    assert state.error in (
        "DOWNLOAD_FAILED",
        "DIGEST_MISMATCH",
        "INCOMPATIBLE_ENVIRONMENT",
        "INSUFFICIENT_SPACE",
        "INVALID_MANIFEST",
    )
    assert snapshot(packages.storage) == before
    assert not (packages.storage / "update-tmp/prepared/plan.json").exists()


def test_duplicate_post_and_browser_disconnect(client, db_session, packages, downloads):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    change_target(packages)
    user = _create_user(db_session, email="d2@example.com", role="admin")
    _login(client, user.email)
    client.app.dependency_overrides[use_cases] = lambda: downloads.updates
    downloads.hold.clear()
    try:
        assert (
            client.post("/api/updates/prepare", json={"version": "1.0.4"}).status_code
            == 202
        )
        assert downloads.entered.wait(5)
        assert (
            client.post("/api/updates/prepare", json={"version": "1.0.4"}).status_code
            == 409
        )
        # No more browser calls: the owned worker completes independently.
        downloads.hold.set()
        assert finish(downloads).phase == "ready"
        assert not (packages.storage / "update-tmp/install-request.json").exists()
    finally:
        client.app.dependency_overrides.pop(use_cases, None)


def test_multiversion_instances_and_stable_artifacts(packages, downloads):
    node(packages.image, "same", "1", "node_modules/a/node_modules/same")
    node(packages.image, "same", "2", "node_modules/d/node_modules/same")
    packages.build()
    first = (packages.seed / "manifest.json").read_bytes()
    import os

    for path in packages.image.rglob("*"):
        if path.is_file():
            os.utime(path, (1234, 5678))
    packages.build()
    assert (packages.seed / "manifest.json").read_bytes() == first
    downloads.updates.prepare(True, "1.0.4")
    state = finish(downloads)
    assert state.phase == "ready", state
    assert state.summary.install == 2
    assert state.summary.keep == 5


def test_legacy_feed_ignores_protocol_two_field(packages, downloads):
    packages.build()
    versions = OfficialReleases(downloads.worker.transport).releases()
    assert versions == [("1.0.4", [])]


def test_local_records_are_not_part_of_target_identity(packages):
    local, baseline = verify_local(packages.storage)
    assert local.identity == packages.initial["identity"]
    assert baseline != local.identity
    assert local == DependencySet.model_validate(packages.initial)


def test_corruption_during_download_cannot_be_ready(packages, downloads):
    change_target(packages)
    downloads.hold.clear()
    downloads.updates.prepare(True, "1.0.4")
    assert downloads.entered.wait(5)
    (packages.storage / "runtime/node_modules/d/index.js").write_text("changed")
    downloads.hold.set()
    assert finish(downloads).error == "LOCAL_DEPENDENCIES_INVALID"


def test_valid_digest_does_not_authorize_archive_escape(packages, downloads):
    import io

    change_target(packages)
    path = packages.output / packages.reference.filename
    manifest = json.loads(path.read_text())
    code = packages.output / manifest["code"]["filename"]
    with tarfile.open(code, "w:gz") as archive:
        member = tarfile.TarInfo("../../escape")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    manifest["code"].update(
        size=code.stat().st_size, sha256=digest(code), expanded_size=1, file_count=1
    )
    path.write_text(json.dumps(manifest))
    packages.reference = packages.reference.model_copy(
        update={"size": path.stat().st_size, "sha256": digest(path)}
    )
    before = snapshot(packages.storage)
    downloads.updates.prepare(True, "1.0.4")
    assert finish(downloads).error == "UNSAFE_ARCHIVE"
    assert snapshot(packages.storage) == before
    assert not (packages.storage / "escape").exists()


def test_target_python_ownership_cannot_overlap(packages):
    payload = json.loads(json.dumps(packages.initial))
    first = next(p for p in payload["packages"] if p["ecosystem"] == "python")
    duplicate = {**first, "name": "other"}
    payload["packages"].append(duplicate)
    payload["identity"] = canonical_digest(
        {k: v for k, v in payload.items() if k != "identity"}
    )
    with pytest.raises(ValueError, match="overlapping Python ownership"):
        DependencySet.model_validate(payload)
