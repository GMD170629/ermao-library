"""Provision an authorized Android probe from the existing release-live fixture.

First start python_release_live_fixture.py in a new evidence directory. This
entry reuses its legal samples and the sample smoke's actual setup/import API
path. It never launches a server, builds a package, installs an APK, clears app
data or handles an existing initialized library. Credentials go directly to a
unique app-private file over adb stdin and never enter an evidence manifest.
The caller owns the fixture stop file and removes the exact adb reverse mapping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps/api-python"))

from app.modules.reader.presentation.v5_schemas import ReaderV5BootstrapResponse
from python_backend_sample_smoke import (
    catalog_resources,
    create_fixture_library,
    expect_ok,
    sha256_file,
    wait_for_task_api,
)

# Match the opt-in acceptance APK's isolated UID; never provision the user's app.
PACKAGE = "com.ermao.library.releasecheck"


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"release fixture requires {field}")
    return value


def require_loopback_origin(value: object) -> tuple[str, int]:
    origin = require_string(value, "apiOrigin")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port in {None, 0}
        or parsed.port in {3000, 3100, 8000}
    ):
        raise ValueError("Android fixture requires its dedicated loopback HTTP origin")
    return origin, parsed.port


def adb_call(adb: str, serial: str, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        [adb, "-s", serial, *args],
        input=stdin,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        # Do not echo input or fixture credentials even if a remote shell fails.
        raise RuntimeError(f"adb {args[0]} failed with exit {result.returncode}")
    return result.stdout


def prepare(manifest_path: Path, adb: str, serial: str, mime_type: str) -> Path:
    if serial.startswith("emulator-") or not serial:
        raise ValueError("an explicitly authorized physical device is required")
    if adb_call(adb, serial, "get-state").strip() != b"device":
        raise RuntimeError("authorized Android device is unavailable")
    manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("release fixture manifest must be an object")
    origin, port = require_loopback_origin(manifest.get("apiOrigin"))
    artifact_dir = Path(
        require_string(manifest.get("artifactDir"), "artifactDir")
    ).resolve()
    evidence_root = (REPO_ROOT / "artifacts/releases/1.0").resolve()
    if not artifact_dir.is_relative_to(evidence_root) or not artifact_dir.is_dir():
        raise ValueError(
            "release fixture must use its existing isolated evidence directory"
        )
    if manifest_path.resolve().parent != artifact_dir:
        raise ValueError("manifest must belong to the exact release fixture directory")
    output = artifact_dir / "android-probe.json"
    if output.exists():
        raise ValueError("Android fixture provisioning requires a new run")
    library_root = Path(
        require_string(manifest.get("libraryRootPath"), "libraryRootPath")
    ).resolve()
    if library_root.parent != artifact_dir or not library_root.is_dir():
        raise ValueError("sample library must be inside this release fixture")
    samples: object = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("release fixture sample manifest is missing")
    originals = {
        path.name: sha256_file(path)
        for path in library_root.iterdir()
        if path.is_file()
    }
    if len(originals) != len(samples):
        raise ValueError("single-file release fixture sample count differs")
    email = require_string(manifest.get("email"), "email")
    password = secrets.token_urlsafe(32)
    with httpx.Client(base_url=origin, timeout=15, follow_redirects=False) as client:
        if (
            expect_ok(client.get("/api/auth/setup/status")).get("initialized")
            is not False
        ):
            raise ValueError("refusing to provision an already initialized server")
        setup = expect_ok(
            client.post(
                "/api/auth/setup",
                json={
                    "name": "Release Android probe",
                    "email": email,
                    "password": password,
                },
            )
        )
        if setup.get("initialized") is not True:
            raise RuntimeError("fresh release setup did not initialize")
        library_id = create_fixture_library(client, library_root)
        wait_for_task_api(client, library_id)
        resources = catalog_resources(
            client, expected_books=len(samples), expected_resources=len(samples)
        )
        selected = [
            resource
            for _, resource in resources
            if any(
                isinstance(asset, dict) and asset.get("mimeType") == mime_type
                for asset in resource.get("assets", [])
            )
        ]
        if len(selected) != 1:
            raise ValueError(
                "requested audio MIME must identify one actual fixture resource"
            )
        resource_id = require_string(selected[0].get("id"), "resourceId")
        response = client.get(f"/api/reader/v5/resources/{resource_id}/bootstrap")
        response.raise_for_status()
        bootstrap = ReaderV5BootstrapResponse.model_validate(response.json()).data
        # The strict response schema contains publication metadata only. Preserve
        # the real wire bytes for cross-language contract diagnosis, not secrets.
        (artifact_dir / "android-bootstrap.json").write_bytes(response.content)
        if (
            bootstrap.reader_type != "audio"
            or len(bootstrap.assets) != 1
            or bootstrap.progress_snapshot is not None
        ):
            raise ValueError(
                "Android probe requires a fresh single-track audio resource"
            )
        asset = bootstrap.assets[0]
        if asset.mime_type != mime_type or asset.duration_ms is None:
            raise ValueError("actual audio asset metadata differs from the probe")
        original = client.get(asset.url)
        original.raise_for_status()
        if hashlib.sha256(original.content).hexdigest() not in originals.values():
            raise AssertionError(
                "served audio original differs from the fixture source"
            )
        private_fixture = {
            "baseUrl": origin,
            "email": email,
            "password": password,
            "bookId": bootstrap.book.id,
            "resourceId": bootstrap.resource.id,
            "assetId": asset.id,
            "mimeType": asset.mime_type,
            "sourceApiPath": asset.url,
            "expectedDurationMillis": asset.duration_ms,
        }
    directory = f"files/rg04-live-{uuid4()}"
    device_file = f"{directory}/fixture.json"
    mapping = f"tcp:{port}"
    mappings = adb_call(adb, serial, "reverse", "--list").decode("utf-8")
    if any(mapping in line.split() for line in mappings.splitlines()):
        raise RuntimeError(
            "the required reverse port is already owned; refusing to replace it"
        )
    adb_call(adb, serial, "reverse", "--no-rebind", mapping, mapping)
    try:
        adb_call(adb, serial, "shell", "-T", "run-as", PACKAGE, "mkdir", directory)
        payload = json.dumps(private_fixture).encode("utf-8")
        adb_call(
            adb,
            serial,
            "shell",
            "-T",
            "run-as",
            PACKAGE,
            "sh",
            "-c",
            f"'cat > {device_file}'",
            stdin=payload,
        )
        observed_hash = (
            adb_call(
                adb, serial, "shell", "-T", "run-as", PACKAGE, "sha256sum", device_file
            )
            .split()[0]
            .decode("ascii")
        )
        if observed_hash != hashlib.sha256(payload).hexdigest():
            raise RuntimeError("private fixture stdin transfer was incomplete")
    except BaseException:
        try:
            adb_call(
                adb, serial, "shell", "-T", "run-as", PACKAGE, "rm", "-f", device_file
            )
        finally:
            adb_call(adb, serial, "reverse", "--remove", mapping)
        raise
    finally:
        private_fixture.clear()
        password = ""
    public = {
        "status": "READY_NOT_TESTED",
        "serial": serial,
        "package": PACKAGE,
        "deviceFixture": f"/data/user/0/{PACKAGE}/{device_file}",
        "deviceEvidenceDirectory": f"/data/user/0/{PACKAGE}/{directory}",
        "reverseMapping": mapping,
        "mimeType": asset.mime_type,
        "bookId": bootstrap.book.id,
        "resourceId": bootstrap.resource.id,
        "assetId": asset.id,
        "expectedDurationMillis": asset.duration_ms,
        "originalSha256ByFilename": originals,
        "provisionerSha256": sha256_file(Path(__file__)),
        "cleanup": "After instrumentation remove this exact reverse mapping and signal the fixture stop file.",
    }
    output.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default=shutil.which("adb"))
    parser.add_argument("--mime-type", default="audio/mpeg")
    args = parser.parse_args()
    if not args.adb:
        parser.error("--adb or an existing adb on PATH is required")
    print(prepare(args.manifest, args.adb, args.serial, args.mime_type))


if __name__ == "__main__":
    main()
