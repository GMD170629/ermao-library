"""Revalidate a confirmed preparation under prepare.lock, before any mutation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sysconfig
from pathlib import Path
from threading import Event

from shuku_dependencies import Artifact, canonical_digest, digest
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
from .archive import check_space, extract_package
from .dependency_preparation import (
    read_bounded,
    verify_dependency_artifact,
    verify_local,
)


def validate_prepared(
    storage: Path,
    state: PreparationState,
    environment: Environment,
    plan_sha256: str,
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
    if (
        len(raw) != reference.size
        or hashlib.sha256(raw).hexdigest() != reference.sha256
    ):
        raise UpdateError("DIGEST_MISMATCH")
    manifest = ReleaseManifest.model_validate_json(raw)
    if (
        manifest.environment != environment
        or reference.environment != environment
        or manifest.version != reference.version
        or manifest.python_abi != sysconfig.get_config_var("SOABI")
    ):
        raise UpdateError("INCOMPATIBLE_ENVIRONMENT")
    plan = json.loads(read_bounded(work / "plan.json", MAX_MANIFEST))
    if (
        canonical_digest(plan) != plan_sha256
        or state.summary.plan_sha256 != plan_sha256
    ):
        raise UpdateError("PLAN_CHANGED")
    local, baseline = verify_local(storage)
    delta = difference(local, manifest.dependencies)
    if (
        plan["baseline"] != baseline
        or plan["manifest_sha256"] != reference.sha256
        or plan["dependency_identity"] != manifest.dependencies.identity
        or plan["version"] != reference.version
        or plan["protocol"] != 2
        or plan["difference"] != delta.model_dump()
    ):
        raise UpdateError("LOCAL_RECORDS_DRIFT")
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
        if (
            path.is_symlink()
            or path.stat().st_size != item.size
            or digest(path) != item.sha256
        ):
            raise UpdateError("DIGEST_MISMATCH")
    expanded = sum(
        verify_dependency_artifact(
            work / p.artifact.filename, p, manifest.dependencies, Event()
        )
        for p in selected
    )
    if expanded > manifest.dependency_expanded_size:
        raise UpdateError("SIZE_LIMIT")
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
    old_links = {x.path: x.target for x in local.node_links}
    new_links = {x.path: x.target for x in manifest.dependencies.node_links}
    for package in manifest.dependencies.packages:
        if (
            package.ecosystem == "node"
            and package_key(package) in delta.keep
            and any(
                old_links.get(name) != new_links.get(name) for name in package.files
            )
        ):
            raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
    database = storage / "database/shuku.sqlite3"
    check_space(
        work,
        2 * code.expanded_size
        + manifest.dependency_expanded_size
        + (2 * database.stat().st_size if database.exists() else 0),
    )
    if extract:
        destination = work / "app"
        if destination.is_symlink():
            raise UpdateError("UNSAFE_STORAGE")
        shutil.rmtree(destination)
        extract_package(
            work / code.filename,
            destination,
            CodePackage(
                version=reference.version, environment=environment, **code.model_dump()
            ),
            Event(),
        )
