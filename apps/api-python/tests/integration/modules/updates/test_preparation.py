from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.modules.updates.application.models import UpdateError
from app.modules.updates.application.preparation import UpdatePreparation
from app.modules.updates.infrastructure import archive as archive_module
from app.modules.updates.infrastructure.archive import program_path
from app.modules.updates.infrastructure.official_source import (
    OfficialHTTP,
    OfficialRedirects,
    OfficialReleases,
)
from app.modules.updates.infrastructure.preparation_worker import PreparationWorker
from app.modules.updates.presentation.http import use_cases

ROOT = Path(__file__).resolve().parents[6]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def real_package(tmp_path_factory):
    directory = tmp_path_factory.mktemp("actual-update-package")
    root = directory / "image"
    standalone = ROOT / "apps/web/.next/standalone"
    assert (standalone / "apps/web/server.js").is_file(), (
        "Run pnpm --filter @shuku/web build first"
    )
    shutil.copytree(standalone, root, symlinks=True)
    for source, destination in (
        ("apps/web/.next/static", "apps/web/.next/static"),
        ("apps/web/public", "apps/web/public"),
        ("apps/api-python/app", "apps/api-python/app"),
    ):
        shutil.copytree(ROOT / source, root / destination, dirs_exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    for name in (
        "scripts/start-unified-app.sh",
        "scripts/unified-http-gateway.mjs",
        "apps/api-python/pyproject.toml",
        "apps/api-python/uv.lock",
    ):
        shutil.copy2(ROOT / name, root / name)
    # Actual build-time environment capture, using this isolated host's runtime.
    command = [
        sys.executable,
        str(ROOT / "scripts/build-runtime-environment.py"),
        "--output",
        str(directory / "environment.json"),
        "--program-root",
        str(root),
    ]
    if sys.platform == "linux":
        import os

        command.extend(
            [
                "--native",
                os.environ.get(
                    "ERMAO_MOBI_CORE_LIBRARY", "/usr/local/lib/libermao_mobi_core.so"
                ),
                "--native",
                os.environ.get(
                    "ERMAO_CHAPTER_CORE_LIBRARY", "/usr/local/lib/libermao_chapters.so"
                ),
            ]
        )
    subprocess.run(command, check=True)
    # Sentinels prove these never enter an application package.
    for name in (
        "storage/database/book.db",
        "apps/api-python/app/.env",
        "apps/web/.next/cache/private",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not ship")
    package = load_script("build-application-package").build_package(
        root, directory / "output"
    )
    return root, package, (directory / "output" / package.filename).read_bytes()


class DownloadFixture:
    def __init__(self, package, body):
        self.package, self.body = package, body
        self.downloads = 0
        self.hold = threading.Event()
        self.hold.set()
        self.entered = threading.Event()
        self.fail = False
        self.packages = [package]

    def feed(self):
        version = self.package.version
        return {
            "schemaVersion": 1,
            "repository": "GMD170629/ermao-library",
            "releases": [
                {
                    "version": version,
                    "tag": f"v{version}",
                    "notesPath": f"v{version}.md",
                    "publishedAt": "2026-09-15T00:00:00Z",
                    "releaseUrl": f"https://github.com/GMD170629/ermao-library/releases/tag/v{version}",
                    "appPackages": [p.model_dump() for p in self.packages],
                }
            ],
        }


@pytest.fixture()
def source(real_package):
    _, package, body = real_package
    fixture = DownloadFixture(package, body)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/index.json"):
                content = json.dumps(fixture.feed()).encode()
            else:
                fixture.downloads += 1
                fixture.entered.set()
                fixture.hold.wait(10)
                if fixture.fail:
                    self.send_error(503)
                    return
                content = fixture.body
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                # Expected when the size-bound test closes its response early.
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()

    class LocalHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            # Inject only the connection. Official URL and redirect checks stay on.
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
    try:
        yield fixture, transport
    finally:
        fixture.hold.set()
        server.shutdown()
        server_thread.join()
        server.server_close()


@pytest.fixture()
def preparation(tmp_path, source):
    fixture, transport = source
    storage = tmp_path / "storage"
    storage.mkdir()
    for name in (
        "runtime/keep",
        "database/keep",
        "secrets/session-secret",
        "covers/keep",
    ):
        path = storage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unchanged")
    books = tmp_path / "books"
    books.mkdir()
    (books / "keep").write_bytes(b"book")
    worker = PreparationWorker(storage, transport)
    updates = UpdatePreparation(
        "1.0.3", fixture.package.environment, OfficialReleases(transport), worker
    )
    try:
        yield updates, worker, storage
    finally:
        fixture.hold.set()
        worker.close()
        for name in (
            "runtime/keep",
            "database/keep",
            "secrets/session-secret",
            "covers/keep",
        ):
            assert (storage / name).read_bytes() == b"unchanged"
        assert sorted(p.name for p in (storage / "runtime").iterdir()) == ["keep"]
        assert (books / "keep").read_bytes() == b"book"


def finished(worker):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = worker.status()
        if state.phase in {"ready", "failed"}:
            return state
        time.sleep(0.02)
    pytest.fail("preparation did not finish")


def test_real_build_download_verification_extraction_and_persistence(
    real_package, preparation, source
):
    root, package, _ = real_package
    updates, worker, storage = preparation
    assert updates.check(True).releases[0].installable
    assert updates.prepare(True, package.version).phase == "downloading"
    state = finished(worker)
    assert state.phase == "ready", state
    assert state.target == package
    assert state.downloaded == package.size
    extracted = storage / "update-tmp/prepared/app"
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if program_path(name):
            target = extracted / name
            if path.is_symlink():
                assert target.is_symlink() and target.readlink() == path.readlink()
            elif path.is_file():
                assert (
                    hashlib.sha256(target.read_bytes()).digest()
                    == hashlib.sha256(path.read_bytes()).digest()
                )
        else:
            assert not (extracted / name).exists()
    assert PreparationWorker(storage, source[1]).status() == state
    assert updates.prepare(True, package.version).phase == "ready"
    assert source[0].downloads == 1


def test_duplicate_operation_and_browser_disconnect(
    client, db_session, preparation, source
):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    updates, worker, _ = preparation
    fixture, _ = source
    user = _create_user(db_session, email="updater@example.com", role="admin")
    _login(client, user.email)
    client.app.dependency_overrides[use_cases] = lambda: updates
    fixture.hold.clear()
    response = client.post(
        "/api/updates/prepare", json={"version": fixture.package.version}
    )
    assert response.status_code == 202
    assert fixture.entered.wait(5)
    assert client.get("/api/health").status_code == 200
    assert (
        client.post(
            "/api/updates/prepare", json={"version": fixture.package.version}
        ).status_code
        == 409
    )
    # No pending HTTP request owns the operation; drop the browser's session.
    client.cookies.clear()
    fixture.hold.set()
    assert finished(worker).phase == "ready"
    assert fixture.downloads == 1


@pytest.mark.parametrize("role", [None, "member"])
def test_authentication_blocks_all_update_endpoints(client, db_session, role):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    if role:
        user = _create_user(db_session, email="member-update@example.com", role=role)
        _login(client, user.email)
    for method, path, body in [
        ("GET", "/api/updates/check", None),
        ("GET", "/api/updates/status", None),
        ("POST", "/api/updates/prepare", {"version": "1.0.4"}),
    ]:
        assert client.request(method, path, json=body).status_code == (
            403 if role else 401
        )


@pytest.mark.parametrize(
    "failure", ["digest", "space", "download", "incompatible", "old", "same", "missing"]
)
def test_preparation_failures_leave_program_and_data_untouched(
    preparation, source, monkeypatch, failure
):
    updates, worker, _ = preparation
    fixture, _ = source
    if failure == "incompatible":
        updates.environment = fixture.package.environment.model_copy(
            update={"compatibility": "0" * 64}
        )
    elif failure in {"old", "same"}:
        updates.current = "1.0.5" if failure == "old" else fixture.package.version
    elif failure == "missing":
        fixture.packages = []
    elif failure == "digest":
        fixture.packages = [fixture.package.model_copy(update={"sha256": "0" * 64})]
    elif failure == "space":
        monkeypatch.setattr(
            archive_module.shutil,
            "disk_usage",
            lambda _: shutil._ntuple_diskusage(1, 1, 0),
        )
    else:
        fixture.fail = True
    if failure in {"incompatible", "old", "same", "missing"}:
        with pytest.raises(UpdateError):
            updates.prepare(True, fixture.package.version)
        assert fixture.downloads == 0
        assert not updates.check(True).releases[0].installable
    else:
        updates.prepare(True, fixture.package.version)
        state = finished(worker)
        assert state.phase == "failed"
        assert (
            state.error
            == {
                "digest": "DIGEST_MISMATCH",
                "space": "INSUFFICIENT_SPACE",
                "download": "DOWNLOAD_FAILED",
            }[failure]
        )
        assert state.failed_phase in {"downloading", "verifying"}


@pytest.mark.parametrize(
    "name,link",
    [
        ("/outside", None),
        ("../outside", None),
        ("node_modules/escape", "../../../../outside"),
        ("node_modules/escape", "/tmp/outside"),
    ],
)
def test_unsafe_archive_never_becomes_ready(preparation, source, name, link):
    updates, worker, storage = preparation
    fixture, _ = source
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        info = tarfile.TarInfo(name)
        if link:
            info.type, info.linkname = tarfile.SYMTYPE, link
        else:
            info.size = 1
        bundle.addfile(info, io.BytesIO(b"x") if not link else None)
    fixture.body = output.getvalue()
    fixture.packages = [
        fixture.package.model_copy(
            update={
                "size": len(fixture.body),
                "sha256": hashlib.sha256(fixture.body).hexdigest(),
                "expanded_size": 1 if not link else 0,
                "file_count": 1,
            }
        )
    ]
    # The manifest's positive expanded-size minimum is retained for link-only tests.
    if link:
        fixture.packages[0] = fixture.packages[0].model_copy(
            update={"expanded_size": 1}
        )
    updates.prepare(True, fixture.package.version)
    state = finished(worker)
    assert state.phase == "failed"
    assert state.error in {"UNSAFE_ARCHIVE", "PACKAGE_IDENTITY_MISMATCH"}
    assert not (storage.parent / "outside").exists()


def test_source_rejects_untrusted_urls_and_redirects():
    with pytest.raises(UpdateError, match="UNTRUSTED_SOURCE"):
        list(OfficialHTTP().chunks("http://127.0.0.1/private", 100, 1))
    handler = OfficialRedirects()
    req = urllib.request.Request(
        "https://github.com/GMD170629/ermao-library/releases/download/v1.0.4/a"
    )
    with pytest.raises(UpdateError, match="UNTRUSTED_SOURCE"):
        handler.redirect_request(req, None, 302, "", {}, "http://127.0.0.1/private")


def test_extra_fields_cross_site_and_application_authorization(
    client, db_session, preparation, source
):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    updates, _, _ = preparation
    user = _create_user(db_session, email="update-security@example.com", role="admin")
    _login(client, user.email)
    client.app.dependency_overrides[use_cases] = lambda: updates
    version = source[0].package.version
    assert (
        client.post(
            "/api/updates/prepare",
            json={"version": version, "url": "http://localhost/private"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/updates/prepare",
            json={"version": version},
            headers={"sec-fetch-site": "cross-site"},
        ).status_code
        == 403
    )
    for call in (
        lambda: updates.prepare(False, version),
        lambda: updates.check(False),
        lambda: updates.status(False),
    ):
        with pytest.raises(UpdateError, match="SYSTEM_MANAGER_REQUIRED"):
            call()
    assert source[0].downloads == 0


def test_abandoned_preparation_is_failed_without_resuming(preparation, source):
    _, worker, storage = preparation
    from app.modules.updates.application.models import PreparationState

    with worker._lock():
        worker._write(PreparationState(phase="extracting", target=source[0].package))
    recovered = PreparationWorker(storage, source[1]).status()
    assert recovered.phase == "failed" and recovered.error == "PREPARATION_INTERRUPTED"
    assert source[0].downloads == 0
    assert not (storage / "update-tmp/prepared").exists()


@pytest.mark.parametrize(
    "field,value", [("size", 1), ("expanded_size", 1), ("file_count", 1)]
)
def test_declared_resource_limits_are_enforced(preparation, source, field, value):
    updates, worker, _ = preparation
    fixture, _ = source
    fixture.packages = [fixture.package.model_copy(update={field: value})]
    updates.prepare(True, fixture.package.version)
    state = finished(worker)
    assert state.phase == "failed"
    assert state.error == "SIZE_LIMIT"


def test_unsupported_deployment_cannot_prepare(preparation, source):
    updates, _, _ = preparation
    updates.environment = None
    assert not updates.check(True).supported
    assert updates.status(True).phase == "idle"
    with pytest.raises(UpdateError, match="UNSUPPORTED_DEPLOYMENT"):
        updates.prepare(True, source[0].package.version)
    assert source[0].downloads == 0


def test_program_version_change_does_not_change_fixed_environment(
    tmp_path, monkeypatch
):
    builder = load_script("build-runtime-environment")
    library = tmp_path / "native-library"
    library.write_bytes(b"original")
    from types import SimpleNamespace

    distributions = list(builder.importlib.metadata.distributions())
    application = SimpleNamespace(
        metadata={"Name": "ermao-books-api-python"},
        version="1.0.4",
        read_text=lambda _: "app-record",
    )
    monkeypatch.setattr(
        builder.importlib.metadata,
        "distributions",
        lambda: [*distributions, application],
    )
    before = builder.snapshot([library])
    application.version = "99.0.0"
    assert builder.snapshot([library])["environment"] == before["environment"]
    library.write_bytes(b"changed dependency")
    assert builder.snapshot([library])["environment"] != before["environment"]


def test_preparation_never_calls_process_control_or_database(
    preparation, source, monkeypatch
):
    import os

    from app.bootstrap import prestart
    from app.db.session import engine

    def forbidden(*args, **kwargs):
        pytest.fail("preparation must not control processes or access the database")

    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(prestart, "main", forbidden)
    monkeypatch.setattr(engine, "connect", forbidden)
    updates, worker, _ = preparation
    updates.prepare(True, source[0].package.version)
    assert finished(worker).phase == "ready"


def test_fixed_environment_comes_from_fixed_metadata_not_package(
    source, monkeypatch, tmp_path
):
    import fcntl
    from types import SimpleNamespace

    from app.modules.updates.infrastructure import environment as detection

    storage = tmp_path / "storage"
    runtime = storage / "runtime"
    runtime.mkdir(parents=True)
    (runtime / ".initialized").touch()
    (runtime / "application.json").write_text("{}")
    fixed = tmp_path / "fixed-environment.json"
    fixed.write_text(
        json.dumps({"environment": source[0].package.environment.model_dump()})
    )
    monkeypatch.setattr(detection, "FIXED_ENVIRONMENT", fixed)
    monkeypatch.setattr(
        detection,
        "__file__",
        str(
            runtime
            / "apps/api-python/app/modules/updates/infrastructure/environment.py"
        ),
    )
    # Exercise the POSIX metadata/lock probe without claiming Linux container QA.
    monkeypatch.setattr(detection, "sys", SimpleNamespace(platform="linux"))
    state = storage / "update-tmp"
    state.mkdir(exist_ok=True)
    with (state / "launcher.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert detection.fixed_environment(storage) == source[0].package.environment
        fixed.unlink()
        assert detection.fixed_environment(storage) is None
    assert detection.fixed_environment(storage) is None


def test_invalid_archive_with_trusted_digest_fails_before_ready(preparation, source):
    updates, worker, _ = preparation
    fixture, _ = source
    fixture.body = b"not a gzip archive"
    fixture.packages = [
        fixture.package.model_copy(
            update={
                "size": len(fixture.body),
                "sha256": hashlib.sha256(fixture.body).hexdigest(),
            }
        )
    ]
    updates.prepare(True, fixture.package.version)
    state = finished(worker)
    assert state.phase == "failed" and state.failed_phase == "extracting"
    assert state.error == "INVALID_ARCHIVE"


def test_download_deadline_is_enforced(source):
    from app.modules.updates.infrastructure.official_source import package_url

    fixture, transport = source
    with pytest.raises(UpdateError, match="DOWNLOAD_TIMEOUT"):
        list(transport.chunks(package_url(fixture.package), fixture.package.size, 0))
