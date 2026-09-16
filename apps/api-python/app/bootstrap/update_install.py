"""Offline preflight invoked by the fixed entry before stopping or changing code."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path

from app.core.config import get_settings
from app.modules.updates.application.models import (
    Environment,
    Package,
    PreparationState,
    ReleaseReference,
    UpdateError,
    version_parts,
)
from app.modules.updates.infrastructure.archive import check_space, extract_package


def validate() -> None:
    settings = get_settings()
    storage = settings.resolved_storage_root
    state_root = storage / "update-tmp"
    request = json.loads((state_root / "install-request.json").read_bytes())
    state = PreparationState.model_validate_json(
        (state_root / "preparation.json").read_bytes()
    )
    package = (
        ReleaseReference if request["target"].get("format") == 2 else Package
    ).model_validate(request["target"])
    environment = Environment.model_validate(
        json.loads(Path("/opt/shuku-launcher/environment.json").read_bytes())[
            "environment"
        ]
    )
    if state.phase != "checking" or state.target != package:
        raise UpdateError("PACKAGE_NOT_READY")
    if package.environment != environment:
        raise UpdateError("INCOMPATIBLE_ENVIRONMENT")
    if request["current"] != settings.app_version or version_parts(
        package.version
    ) <= version_parts(settings.app_version):
        raise UpdateError("NOT_NEWER")
    if isinstance(package, ReleaseReference):
        from app.modules.updates.infrastructure.install_plan import validate_prepared

        validate_prepared(
            storage, state, environment, request["plan_sha256"], extract=True
        )
        return
    work = state_root / "prepared"
    archive = work / "application.tar.gz"
    if work.is_symlink() or archive.is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    if archive.stat().st_size != package.size:
        raise UpdateError("DIGEST_MISMATCH")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != package.sha256:
            raise UpdateError("DIGEST_MISMATCH")
    check_space(
        work, package.expanded_size * 2 + settings.database_path.stat().st_size * 2
    )
    # Re-extract the trusted archive under the installation lock. Never trust a
    # stale/mutated extracted tree; same protocol and extractor as preparation.
    destination = work / "app"
    if destination.is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    shutil.rmtree(destination)
    extract_package(archive, destination, package, threading.Event())


if __name__ == "__main__":
    import sys

    try:
        validate()
    except Exception as error:  # noqa: BLE001 - offline command boundary
        code = error.code if isinstance(error, UpdateError) else "PREFLIGHT_FAILED"
        print(f"application_update preflight={code}", file=sys.stderr, flush=True)
        sys.exit(1)
