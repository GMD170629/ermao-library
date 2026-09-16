#!/usr/bin/env python3
"""Explicit D2 acceptance inside the D1 image with this checkout mounted at /source.

Run: docker run --rm --network none -v "$PWD:/source:ro" --entrypoint python
     shuku-d1:local /source/scripts/accept_dependency_preparation.py
No application service, migration or installer is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "apps/api-python"))
sys.path.insert(0, str(SOURCE / "scripts"))


def snapshot(root: Path) -> str:
    result = []
    for path in sorted(root.rglob("*")):
        if "update-tmp" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            content = str(path.readlink())
        elif path.is_file():
            with path.open("rb") as stream:
                content = hashlib.file_digest(stream, "sha256").hexdigest()
        else:
            continue
        result.append(
            (
                str(path.relative_to(root)),
                content,
                path.lstat().st_mtime_ns,
                path.lstat().st_mode,
            )
        )
    return hashlib.sha256(json.dumps(result).encode()).hexdigest()


def exercise(root: Path) -> None:
    from app.modules.updates.application.models import ReleaseReference
    from app.modules.updates.infrastructure.official_source import (
        OfficialHTTP,
        OfficialRedirects,
    )
    from app.modules.updates.infrastructure.preparation_worker import PreparationWorker
    from shuku_dependencies import generate

    storage, image, seed, output = (
        root / name for name in ("storage", "image", "seed", "output")
    )
    shutil.copytree("/opt/shuku-image", image, symlinks=True)
    # Real D1 standalone and target wheels; current Python protocol implementation.
    shutil.copytree(
        SOURCE / "apps/api-python/app",
        image / "apps/api-python/app",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        SOURCE / "apps/api-python/shuku_dependencies",
        image / "apps/api-python/shuku_dependencies",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree("/opt/shuku-dependency-seed", seed)
    original = json.loads((seed / "manifest.json").read_text())
    chosen = next(
        p
        for p in sorted(original["packages"], key=lambda p: p["artifact"]["size"])
        if p["ecosystem"] == "node" and any(f.endswith(".js") for f in p["files"])
    )
    changed = next(f for f in chosen["files"] if f.endswith(".js"))
    with (image / changed).open("a") as stream:
        stream.write("\n// D2 isolated same-version artifact replacement fixture\n")
    (seed / "manifest.json").write_text(json.dumps(generate(image, seed)))
    spec = importlib.util.spec_from_file_location(
        "build_release", SOURCE / "scripts/build-application-package.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    reference = ReleaseReference.model_validate(
        builder.build_release(
            image, output, seed, Path("/opt/shuku-launcher/environment.json")
        )
    )
    manifest = json.loads((output / reference.filename).read_text())
    import tarfile

    with tarfile.open(output / manifest["code"]["filename"]) as archive:
        assert not any(
            "node_modules" in Path(member.name).parts
            or "/dependencies/python/" in member.name
            for member in archive
        )
    before = snapshot(storage)
    requests, counts = Counter(), Counter()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.rsplit("/", 1)[-1]
            requests[name] += 1
            data = (output / name).read_bytes()
            counts[name] += len(data)
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
    worker = PreparationWorker(storage, transport, reference.environment)
    try:
        worker.submit(reference)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = worker.status()
            if state.phase in ("ready", "failed"):
                break
            time.sleep(0.05)
        assert state.phase == "ready", state
        assert state.summary.install == 1
        assert state.summary.keep == len(original["packages"]) - 1
        assert len(requests) == 3 and all(value == 1 for value in requests.values())
        assert sum(counts.values()) == state.downloaded
        assert snapshot(storage) == before
        assert not (storage / "update-tmp/install-request.json").exists()
        print(
            json.dumps(
                {
                    "phase": state.phase,
                    "selected_instance": chosen["location"],
                    "requests": dict(requests),
                    "bytes": dict(counts),
                    "summary": state.summary.model_dump(),
                    "business_snapshot_before_after": before,
                },
                indent=2,
            )
        )
    finally:
        worker.close()
        server.shutdown()
        thread.join()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.root:
        exercise(args.root)
        return
    from dependency_environment import initialize_dependencies

    with tempfile.TemporaryDirectory(prefix="shuku-d2-acceptance-") as temporary:
        root = Path(temporary)
        storage = root / "storage"
        storage.mkdir()
        shutil.copytree("/opt/shuku-image", storage / "runtime", symlinks=True)
        initialize_dependencies(storage, Path("/opt/shuku-dependency-seed"))
        for name in (
            "database/shuku.sqlite3",
            "books/book",
            "secrets/session-secret",
            "covers/book",
        ):
            path = storage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"no preparation writes")
        subprocess.run(
            [
                str(storage / "dependencies/python/bin/python"),
                "-B",
                str(Path(__file__)),
                "--root",
                str(root),
            ],
            check=True,
            env={**os.environ, "PYTHONNOUSERSITE": "1"},
        )


if __name__ == "__main__":
    main()
