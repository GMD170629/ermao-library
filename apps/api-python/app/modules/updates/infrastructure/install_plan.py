"""Revalidate a confirmed preparation under prepare.lock, before any mutation."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from threading import Event

from shuku_dependencies import Artifact, digest
from shuku_dependencies.installed import bounded_json, wheel_install_paths

from ..application.dependency_release import (
    MAX_MANIFEST,
    CodePackage,
    ReleaseManifest,
    difference,
    package_key,
)
from ..application.models import (
    Environment,
    PreparationState,
    ReleaseReference,
    UpdateError,
)
from .archive import extract_package
from .dependency_preparation import (
    read_bounded,
    read_local,
    verify_dependency_artifact,
)


def validate_prepared(
    storage: Path,
    state: PreparationState,
    environment: Environment,
    plan_sha256: str | None,
    *,
    extract: bool = False,
) -> None:
    reference = state.target
    if not isinstance(reference, ReleaseReference) or state.summary is None:
        raise UpdateError("PACKAGE_NOT_READY")
    work = storage / "update-tmp/prepared"
    if work.is_symlink() or (storage / "update-tmp").is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    raw = read_bounded(work / "release.json", MAX_MANIFEST)
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise UpdateError("DIGEST_MISMATCH")
    manifest = ReleaseManifest.model_validate_json(raw, context={"runtime": True})
    local, _ = read_local(storage)
    delta = difference(local, manifest.dependencies)
    selected = [
        p for p in manifest.dependencies.packages if package_key(p) in delta.install
    ]
    code = manifest.code
    artifacts: list[Artifact] = [
        Artifact(code.filename, code.size, code.sha256),
        *(p.artifact for p in selected),
    ]
    for item in artifacts:
        path = work / item.filename
        if path.is_symlink() or digest(path) != item.sha256:
            raise UpdateError("DIGEST_MISMATCH")
    for package in selected:
        verify_dependency_artifact(
            work / package.artifact.filename,
            package,
            manifest.dependencies,
            Event(),
            verify_identity=False,
        )
    # A valid wheel may still collide with a kept package's generated console script.
    installed = bounded_json(storage / "dependencies/installed.json")
    owners = {
        f["path"]
        for r in installed["python_records"]
        if "python:" + r["name"] in delta.keep
        for f in r["files"]
    }
    for package in selected:
        if package.ecosystem == "python":
            from dataclasses import asdict

            paths = wheel_install_paths(
                storage / "dependencies/python",
                asdict(package),
                work / package.artifact.filename,
            )
            if owners & paths:
                raise UpdateError("DEPENDENCY_OWNERSHIP_CONFLICT")
            owners.update(paths)
    if extract:
        destination = work / "app"
        if destination.is_symlink():
            raise UpdateError("UNSAFE_STORAGE")
        if destination.exists():
            shutil.rmtree(destination)
        extract_package(
            work / code.filename,
            destination,
            CodePackage.model_validate(
                dict(
                    version=reference.version,
                    environment=environment,
                    **code.model_dump(),
                ),
                context={"runtime": True},
            ),
            Event(),
            verify_identity=False,
        )
