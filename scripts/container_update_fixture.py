"""Explicit Docker acceptance fixture. Run only inside its disposable container."""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import shutil
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/app/storage/runtime/apps/api-python")

from app.core.config import get_settings
from app.db.runner import head_revision
from app.db.session import SessionLocal, engine
from app.models import Library, ReaderResourceProgress, SystemSetting, User
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.updates.application.models import Environment
from app.modules.updates.application.preparation import UpdatePreparation
from app.modules.updates.infrastructure.official_source import (
    OfficialHTTP,
    OfficialRedirects,
    OfficialReleases,
)
from app.modules.updates.infrastructure.preparation_worker import PreparationWorker


def main():
    assert Path("/acceptance-only").exists(), "isolated acceptance container required"
    storage = get_settings().resolved_storage_root
    # Populate real records with valid FK relationships, using existing ORM.
    with SessionLocal() as db:
        user = db.query(User).one()
        db.add(
            Library(
                id="acceptance",
                name="Acceptance",
                root_path="/books",
                organization_mode="FLAT",
                enabled=False,
            )
        )
        db.flush()
        db.add(
            LibrarySourceNode(
                id="acceptance-node",
                library_id="acceptance",
                relative_path="book.txt",
                path_key="v1:" + hashlib.sha256(b"book.txt").hexdigest(),
                name="book.txt",
                physical_kind="REGULAR_FILE",
                observed_size_bytes=4,
                observed_mtime_ns=1,
                observed_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add(
            LibraryBook(
                id="acceptance-book",
                library_id="acceptance",
                source_node_id="acceptance-node",
            )
        )
        db.flush()
        db.add(
            LibraryReadableResource(
                id="acceptance-resource",
                library_id="acceptance",
                book_id="acceptance-book",
                source_node_id="acceptance-node",
                adapter_id="txt",
                adapter_version="1",
                format="TXT",
                enablement_state="ENABLED",
                import_state="READY",
            )
        )
        db.flush()
        db.add(
            LibraryResourceAsset(
                id="acceptance-asset",
                library_id="acceptance",
                resource_id="acceptance-resource",
                source_node_id="acceptance-node",
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            )
        )
        db.flush()
        db.add(
            ReaderResourceProgress(
                id="acceptance-progress",
                user_id=user.id,
                resource_id="acceptance-resource",
                reader_type="TXT",
                position="42",
                percent=0.42,
                extra="{}",
            )
        )
        db.add(SystemSetting(key="acceptance-preserved", value="configuration"))
        if "--build-only" in sys.argv:
            db.add(
                Library(
                    id="acceptance-reader",
                    name="Reader acceptance",
                    root_path="/books/reader",
                    organization_mode="FLAT",
                    enabled=True,
                )
            )
        db.commit()
    if "--seed-only" in sys.argv:
        return
    root = Path("/tmp/update-fixture/image")
    shutil.copytree("/opt/shuku-image", root, symlinks=True)
    current = get_settings().app_version
    major, minor, patch = map(int, current.split("."))
    version = f"{major}.{minor}.{patch + 1}"
    for name in (
        "apps/web/package.json",
        "apps/web/public/sw.js",
        "apps/api-python/pyproject.toml",
        "apps/api-python/app/core/config.py",
        "application.json",
    ):
        path = root / name
        path.write_text(path.read_text().replace(current, version))
    if "--build-only" in sys.argv and "--dependencies" not in sys.argv:
        # Real B Next build, including the matching service worker and static assets.
        web = Path("/acceptance-web")
        assert (
            json.loads((web / "standalone/apps/web/package.json").read_text())[
                "version"
            ]
            == version
        )
        for directory in (root / "apps/web", root / "node_modules"):
            shutil.rmtree(directory)
        shutil.copytree(web / "standalone", root, dirs_exist_ok=True, symlinks=True)
        shutil.copytree(
            web / "static", root / "apps/web/.next/static", dirs_exist_ok=True
        )
        shutil.copytree(web / "public", root / "apps/web/public", dirs_exist_ok=True)
    # Isolated B code behavior and migration, never the formal source/version chain.
    health = root / "apps/api-python/app/modules/system/presentation/health.py"
    health.write_text(
        health.read_text().replace(
            "    health_status = run_system_health_checks",
            '    response.headers["X-Acceptance-Code"] = "B"\n    health_status = run_system_health_checks',
            1,
        )
    )
    revision = head_revision(engine)
    (root / "apps/api-python/app/db/alembic/versions/acceptance_only.py").write_text(
        f"from alembic import op\nimport sqlalchemy as sa\nrevision='acceptance_b'\ndown_revision={revision!r}\nbranch_labels=None\ndepends_on=None\ndef upgrade():\n    op.create_table('AcceptanceMigration', sa.Column('id', sa.Integer, primary_key=True))\ndef downgrade():\n    raise RuntimeError('not supported')\n"
    )
    (storage / "runtime/obsolete-acceptance-file").write_text("remove on B")
    spec = importlib.util.spec_from_file_location(
        "packager", "/tooling/scripts/build-application-package.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if "--dependencies" in sys.argv:
        from dependency_update_fixture import target_dependencies

        from app.modules.updates.application.models import ReleaseReference

        seed = root.parent / "dependency-seed"
        shutil.copytree("/opt/shuku-dependency-seed", seed)
        target_dependencies(root, seed)
        health.write_text(
            health.read_text().replace(
                '    response.headers["X-Acceptance-Code"]',
                '    from d3_namespace.b import VALUE\n    response.headers["X-Acceptance-Dependency"] = str(VALUE)\n    response.headers["X-Acceptance-Code"]',
            )
        )
        migration = root / "apps/api-python/app/db/alembic/versions/acceptance_only.py"
        migration.write_text(
            migration.read_text().replace(
                "def upgrade():",
                "def upgrade():\n    from d3_namespace.b import VALUE\n    from d3_namespace.e import VALUE as ADDED\n    assert VALUE == 2 and ADDED == 1",
            )
        )
        package = ReleaseReference.model_validate(
            module.build_release(
                root,
                root.parent / "output",
                seed,
                Path("/opt/shuku-launcher/environment.json"),
            )
        )
    else:
        package = module.build_package(root, root.parent / "output")
    if "--two-updates" in sys.argv:
        next_version = f"{major}.{minor}.{patch + 2}"
        for name in (
            "apps/web/package.json",
            "apps/web/public/sw.js",
            "apps/api-python/pyproject.toml",
            "apps/api-python/app/core/config.py",
            "application.json",
        ):
            path = root / name
            path.write_text(path.read_text().replace(version, next_version))
        health.write_text(health.read_text().replace('Code"] = "B"', 'Code"] = "C"'))
        next_package = module.build_release(
            root,
            root.parent / "output-c",
            seed,
            Path("/opt/shuku-launcher/environment.json"),
        )
    body = (root.parent / "output" / package.filename).read_bytes()
    feed = {
        "schemaVersion": 1,
        "repository": "GMD170629/ermao-library",
        "releases": [
            {
                "version": version,
                "tag": f"v{version}",
                "notesPath": f"v{version}.md",
                "publishedAt": "2026-09-15T00:00:00Z",
                "releaseUrl": f"https://github.com/GMD170629/ermao-library/releases/tag/v{version}",
                (
                    "dependencyReleases"
                    if "--dependencies" in sys.argv
                    else "appPackages"
                ): [package.model_dump()],
            }
        ],
    }

    (root.parent / "output/index.json").write_text(json.dumps(feed))
    if "--two-updates" in sys.argv:
        next_feed = json.loads(json.dumps(feed))
        item = next_feed["releases"][0]
        item.update(
            version=next_version,
            tag=f"v{next_version}",
            notesPath=f"v{next_version}.md",
            releaseUrl=f"https://github.com/GMD170629/ermao-library/releases/tag/v{next_version}",
            dependencyReleases=[next_package],
        )
        (root.parent / "output-c/index.json").write_text(json.dumps(next_feed))
    if "--build-only" in sys.argv:
        print(
            json.dumps(
                {"target": version, "sha256": package.sha256, "size": package.size}
            )
        )
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content = (
                json.dumps(feed).encode() if self.path.endswith("index.json") else body
            )
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
                lambda host, **kw: http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, **kw
                ),
                request,
            )

    transport = OfficialHTTP(
        urllib.request.build_opener(
            urllib.request.ProxyHandler({}), OfficialRedirects(), LocalHTTPS()
        )
    )
    environment = Environment.model_validate(
        json.loads(Path("/opt/shuku-launcher/environment.json").read_text())[
            "environment"
        ]
    )
    worker = PreparationWorker(storage, transport)
    try:
        updates = UpdatePreparation(
            current, environment, OfficialReleases(transport), worker
        )
        assert updates.check(True).releases[0].installable
        updates.prepare(True, version)
        deadline = time.monotonic() + 60
        while (
            worker.status().phase not in {"ready", "failed"}
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        assert worker.status().phase == "ready", worker.status()
        print(
            json.dumps(
                {"target": version, "sha256": package.sha256, "size": package.size}
            )
        )
    finally:
        worker.close()
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    main()
