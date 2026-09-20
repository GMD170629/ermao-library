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
    PreparationState,
    ReleaseReference,
    UpdateError,
    parse_target,
    version_parts,
)
from app.modules.updates.infrastructure.archive import extract_package


def validate() -> None:
    settings = get_settings()
    storage = settings.resolved_storage_root
    state_root = storage / "update-tmp"
    request = json.loads((state_root / "install-request.json").read_bytes())
    state = PreparationState.model_validate_json(
        (state_root / "preparation.json").read_bytes()
    )
    # Use the persisted target contract, including the immutable GHCR digest.
    package = parse_target(request["target"])
    environment = Environment.model_validate(
        json.loads(Path("/opt/shuku-launcher/environment.json").read_bytes())[
            "environment"
        ]
    )
    if (
        state.phase != "checking"
        or state.target is None
        or (state.target.version, state.target.sha256, state.target.format)
        != (package.version, package.sha256, package.format)
    ):
        raise UpdateError("PACKAGE_NOT_READY")
    if request["current"] != settings.app_version or version_parts(
        package.version
    ) <= version_parts(settings.app_version):
        raise UpdateError("NOT_NEWER")
    if isinstance(package, ReleaseReference):
        from app.modules.updates.infrastructure.install_plan import validate_prepared

        validate_prepared(
            storage, state, environment, request.get("plan_sha256"), extract=True
        )
        return
    work = state_root / "prepared"
    archive = work / "application.tar.gz"
    if work.is_symlink() or archive.is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != package.sha256:
            raise UpdateError("DIGEST_MISMATCH")
    # Re-extract the trusted archive under the installation lock. Never trust a
    # stale/mutated extracted tree; same protocol and extractor as preparation.
    destination = work / "app"
    if destination.is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    if destination.exists():
        shutil.rmtree(destination)
    extract_package(
        archive, destination, package, threading.Event(), verify_identity=False
    )


if __name__ == "__main__":
    import errno
    import os
    import sys

    try:
        validate()
    except Exception as error:  # noqa: BLE001 - offline command boundary
        if isinstance(error, UpdateError):
            code = error.code
        elif isinstance(error, PermissionError):
            code = "STORAGE_NOT_WRITABLE"
        elif isinstance(error, FileNotFoundError):
            code = "PACKAGE_NOT_READY"
        elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
            code = "INSUFFICIENT_SPACE"
        elif isinstance(error, (ValueError, KeyError, TypeError)):
            code = "INVALID_INSTALL_REQUEST"
        else:
            code = "PREFLIGHT_FAILED"
        message = f"application_update preflight={code}"
        print(message, file=sys.stderr, flush=True)
        try:
            log = get_settings().resolved_storage_root / "update-tmp/installation.log"
            with os.fdopen(
                os.open(log, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW), "a"
            ) as output:
                output.write(message + "\n")
        except (OSError, ValueError):
            print(
                "application_update preflight_log=WRITE_FAILED",
                file=sys.stderr,
                flush=True,
            )
        sys.exit(1)
