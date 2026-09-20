from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.modules.updates.application.models import UpdateError
from app.modules.updates.application.preparation import UpdatePreparation
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
def program_package(tmp_path_factory):
    """Protocol fixture only: no Web build, host inventory or native installation."""
    directory = tmp_path_factory.mktemp("protocol-update-package")
    root = directory / "image"
    files = {
        "scripts/start-unified-app.sh": "#!/bin/sh\nexit 0\n",
        "scripts/unified-http-gateway.mjs": "export {};\n",
        "apps/web/server.js": "console.log('protocol fixture');\n",
        "apps/web/package.json": '{"version":"1.0.4"}',
        "apps/web/.next/BUILD_ID": "protocol-fixture",
        "apps/web/.next/server/page.js": "export {};\n",
        "apps/web/.next/static/chunk.js": "export {};\n",
        "apps/web/public/icon.svg": "<svg/>",
        "apps/api-python/app/main.py": "# protocol fixture\n",
        "apps/api-python/app/worker/main.py": "# protocol fixture\n",
        "apps/api-python/app/bootstrap/prestart.py": "# protocol fixture\n",
        "apps/api-python/app/db/alembic.ini": "[alembic]\n",
        "apps/api-python/app/db/alembic/versions/initial.py": "# migration fixture\n",
        "apps/api-python/app/core/config.py": 'app_version: str = "1.0.4"\n',
        "apps/api-python/pyproject.toml": '[project]\nversion = "1.0.4"\n',
        "apps/api-python/uv.lock": "version = 1\n",
        "node_modules/dependency/index.js": "module.exports = {};\n",
        "storage/database/book.db": "must not ship",
        "apps/api-python/app/.env": "must not ship",
        "apps/web/.next/cache/private": "must not ship",
        "application.json": json.dumps(
            {
                "version": "1.0.4",
                "environment": {
                    "format": 1,
                    "platform": "linux-x86_64",
                    "compatibility": "a" * 64,
                },
            }
        ),
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / "apps/web/node_modules").symlink_to(
        "../../node_modules", target_is_directory=True
    )
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
def source(program_package):
    _, package, body = program_package
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


def assert_package_prepared(program_package, preparation, source):
    root, package, _ = program_package
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


def test_historical_failure_marker_does_not_block_preparation(
    program_package, preparation, source
):
    _, worker, _ = preparation
    worker.root.mkdir(exist_ok=True)
    marker = worker.root / "installation-incomplete"
    marker.write_text("previous failure")
    assert_package_prepared(program_package, preparation, source)
    assert marker.read_text() == "previous failure"


def test_package_download_verification_extraction_and_persistence(
    program_package, preparation, source
):
    assert_package_prepared(program_package, preparation, source)


@pytest.mark.parametrize(
    "name",
    [
        "apps/web/package.json",
        "apps/api-python/pyproject.toml",
        "apps/api-python/app/core/config.py",
    ],
)
def test_packager_rejects_version_mismatch(program_package, tmp_path, name):
    root = tmp_path / "image"
    shutil.copytree(program_package[0], root, symlinks=True)
    path = root / name
    path.write_text(path.read_text().replace("1.0.4", "1.0.5"))
    with pytest.raises(ValueError, match="application versions disagree"):
        load_script("build-application-package").build_package(
            root, tmp_path / "output"
        )


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
            update={"platform": "linux-aarch64"}
        )
    elif failure in {"old", "same"}:
        updates.current = "1.0.5" if failure == "old" else fixture.package.version
    elif failure == "missing":
        fixture.packages = []
    elif failure == "digest":
        fixture.packages = [fixture.package.model_copy(update={"sha256": "0" * 64})]
    elif failure == "space":
        monkeypatch.setattr(
            worker,
            "_download",
            lambda *args: (_ for _ in ()).throw(OSError(28, "disk full")),
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
def test_declared_sizes_do_not_override_valid_digest(preparation, source, field, value):
    updates, worker, _ = preparation
    fixture, _ = source
    fixture.packages = [fixture.package.model_copy(update={field: value})]
    updates.prepare(True, fixture.package.version)
    state = finished(worker)
    assert state.phase == "ready"
    assert state.downloaded == len(fixture.body)


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

    # Deterministic inventory: exercise hashing without inspecting this host.
    binary = tmp_path / "fixed-runtime-binary"
    binary.write_bytes(b"fixed interpreter")
    distributions = [
        SimpleNamespace(
            metadata={"Name": "dependency"},
            version="1.0",
            read_text=lambda _: "dependency-record",
        )
    ]
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(builder.platform, "python_version", lambda: "3.11.0")
    monkeypatch.setattr(
        builder, "sys", SimpleNamespace(platform="linux", executable=str(binary))
    )
    monkeypatch.setattr(
        builder.sysconfig,
        "get_config_var",
        lambda key: {
            "LIBDIR": str(tmp_path),
            "LDLIBRARY": binary.name,
            "SOABI": "test-abi",
        }[key],
    )
    monkeypatch.setattr(
        builder.subprocess, "check_output", lambda *a, **k: "test-system=1\n"
    )
    monkeypatch.setattr(shutil, "which", lambda _: str(binary))
    application = SimpleNamespace(
        metadata={"Name": "ermao-books-api-python"},
        version="1.0.4",
        read_text=lambda _: "app-record",
    )
    monkeypatch.setattr(
        __import__("importlib.metadata", fromlist=["metadata"]),
        "distributions",
        lambda: [*distributions, application],
    )
    before = builder.snapshot([library])
    application.version = "99.0.0"
    assert builder.snapshot([library])["environment"] == before["environment"]
    distributions[0].version = "2.0"
    assert builder.snapshot([library])["environment"] == before["environment"]
    library.write_bytes(b"changed fixed native dependency")
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
    (tmp_path / "container_install.py").touch()
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
        fixed.write_text(
            json.dumps(
                {
                    "environment": source[0].package.environment.model_dump(),
                    "inventory": {"launcher_protocol": 2},
                }
            )
        )
        assert detection.fixed_environment(storage) == source[0].package.environment
        assert detection.fixed_protocol() == 2
        assert detection.fixed_install_protocol() == 0
        (tmp_path / "dependency_install.py").touch()
        (tmp_path / "shuku_dependencies").mkdir()
        (tmp_path / "shuku_dependencies/installed.py").touch()
        assert detection.fixed_install_protocol() == 2
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


@pytest.mark.parametrize("role", [None, "member"])
def test_install_requires_system_manager(client, db_session, role):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    if role:
        user = _create_user(db_session, email="install-member@example.com", role=role)
        _login(client, user.email)
    assert client.post(
        "/api/updates/install", json={"version": "1.0.4", "sha256": "a" * 64}
    ).status_code == (403 if role else 401)


def test_install_reserves_prepared_source(client, db_session, preparation, source):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    updates, worker, storage = preparation
    package = source[0].package
    user = _create_user(db_session, email="installer@example.com", role="admin")
    _login(client, user.email)
    client.app.dependency_overrides[use_cases] = lambda: updates
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": package.sha256},
        ).status_code
        == 400
    )
    updates.prepare(True, package.version)
    assert finished(worker).phase == "ready"
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": "0" * 64},
        ).status_code
        == 400
    )
    assert not (storage / "update-tmp/install-request.json").exists()
    assert worker.status().phase == "ready"
    archive = storage / "update-tmp/prepared/application.tar.gz"
    before = archive.read_bytes()
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": package.sha256},
            headers={"sec-fetch-site": "cross-site"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": package.sha256, "path": "/tmp"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": package.sha256},
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/updates/install",
            json={"version": package.version, "sha256": package.sha256},
        ).status_code
        == 409
    )
    with pytest.raises(UpdateError, match="UPDATE_BUSY"):
        worker.submit(package)
    assert archive.read_bytes() == before
    assert worker.status().phase == "requested"
    assert (
        json.loads((storage / "update-tmp/install-request.json").read_bytes())["target"]
        == package.model_dump()
    )


@pytest.mark.parametrize("kind", ["download", "kindle", "logs", "metadata", "organize"])
def test_background_shutdown_waits_for_current_task(kind):
    from app.services.download_queue import DownloadQueueWorker
    from app.services.kindle_queue import KindleSendQueueWorker
    from app.services.log_maintenance import SystemEventMaintenanceWorker
    from app.services.metadata_lookup_queue import MetadataLookupWorker
    from app.services.organize_scheduler import OrganizerScheduler

    cls, event_name, stop_name = {
        "download": (DownloadQueueWorker, "_stop_event", "stop"),
        "kindle": (KindleSendQueueWorker, "_stop_event", "stop"),
        "logs": (SystemEventMaintenanceWorker, "_stop", "stop"),
        "metadata": (MetadataLookupWorker, "_stop", "shutdown"),
        "organize": (OrganizerScheduler, "_stop", "shutdown"),
    }[kind]
    worker = cls.__new__(cls)
    stop = threading.Event()
    release = threading.Event()
    entered = threading.Event()
    setattr(worker, event_name, stop)

    def current_task():
        entered.set()
        release.wait(5)

    worker._thread = threading.Thread(target=current_task)
    worker._thread.start()
    assert entered.wait(1)
    worker.request_stop()
    assert stop.is_set()
    joining = threading.Thread(target=getattr(worker, stop_name))
    joining.start()
    try:
        joining.join(0.05)
        assert joining.is_alive(), "shutdown must not abandon current business work"
    finally:
        release.set()
        joining.join(2)
        worker._thread.join(2)
    assert not joining.is_alive()


def test_runtime_information_uses_actual_backend_and_requires_login(
    client, db_session, preparation
):
    from tests.contract.api.test_system_management_authorization import (
        _create_user,
        _login,
    )

    updates, _, _ = preparation
    client.app.dependency_overrides[use_cases] = lambda: updates
    assert client.get("/api/updates/runtime").status_code == 401
    user = _create_user(db_session, email="runtime-member@example.com", role="member")
    _login(client, user.email)
    result = client.get("/api/updates/runtime")
    assert result.status_code == 200
    assert result.json()["data"] == {
        "current_version": updates.current,
        "supported": True,
        "install_protocol": 1,
    }
    assert client.get("/api/updates/status").status_code == 403


def test_protocol_two_cannot_be_parsed_as_legacy_package(source):
    from pydantic import ValidationError

    from app.modules.updates.application.models import ApplicationIdentity, Package

    package = source[0].package.model_dump()
    package["format"] = 2
    with pytest.raises(ValidationError):
        Package.model_validate(package)
    with pytest.raises(ValidationError):
        ApplicationIdentity.model_validate(
            {
                "version": source[0].package.version,
                "environment": source[0].package.environment.model_dump(),
                "protocol": 2,
            }
        )


@pytest.mark.parametrize("limit", ["bytes", "files", "total"])
def test_fixed_resource_caps_still_protect_runtime(
    preparation, source, monkeypatch, limit
):
    updates, worker, _ = preparation
    fixture, _ = source
    if limit in {"bytes", "total"}:
        name = "MAX_PACKAGE" if limit == "bytes" else "MAX_TOTAL"
        monkeypatch.setattr(
            f"app.modules.updates.infrastructure.preparation_worker.{name}", 1
        )
    else:
        monkeypatch.setattr("app.modules.updates.infrastructure.archive.MAX_FILES", 1)
    updates.prepare(True, fixture.package.version)
    state = finished(worker)
    assert state.phase == "failed"
    assert state.error == "SIZE_LIMIT"
