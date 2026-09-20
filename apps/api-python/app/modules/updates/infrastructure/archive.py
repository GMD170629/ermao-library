"""The one application-package layout and bounded, link-safe extraction."""

from __future__ import annotations

import gzip
import io
import os
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from threading import Event

from ..application.dependency_release import CodePackage, ProgramIdentity
from ..application.models import (
    MAX_EXPANDED,
    MAX_FILES,
    ApplicationIdentity,
    Package,
    UpdateError,
)

REQUIRED = (
    "scripts/start-unified-app.sh",
    "scripts/unified-http-gateway.mjs",
    "apps/web/server.js",
    "apps/web/.next/BUILD_ID",
    "apps/web/.next/server",
    "apps/web/.next/static",
    "apps/web/public",
    "apps/api-python/app/main.py",
    "apps/api-python/app/worker/main.py",
    "apps/api-python/app/bootstrap/prestart.py",
    "apps/api-python/app/db/alembic.ini",
    "apps/api-python/app/db/alembic/versions",
    "apps/api-python/pyproject.toml",
    "apps/api-python/uv.lock",
    "application.json",
    "node_modules",
)


def program_path(name: str, protocol: int = 1) -> bool:
    parts = PurePosixPath(name).parts
    if protocol == 2 and "node_modules" in parts:
        return False
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(p in {".", ".."} for p in name.split("/"))
    ):
        return False
    if any(
        p in {"__pycache__", ".git", ".venv", "storage", "secrets"}
        or p.startswith(".env")
        or p.endswith(".pyc")
        for p in parts
    ):
        return False
    if name == "apps/web/.next/cache" or name.startswith("apps/web/.next/cache/"):
        return False
    return (
        name
        in {
            "apps",
            "apps/web",
            "apps/api-python",
            "scripts",
            "application.json",
            "node_modules",
            "package.json",
        }
        or name.startswith(
            (
                "apps/web/",
                "apps/api-python/app/",
                "apps/api-python/shuku_dependencies/",
                "node_modules/",
            )
        )
        or name
        in {
            "apps/api-python/app",
            "apps/api-python/shuku_dependencies",
            "apps/api-python/pyproject.toml",
            "apps/api-python/uv.lock",
            "scripts/start-unified-app.sh",
            "scripts/unified-http-gateway.mjs",
        }
    )


def validate_layout(
    root: Path, identity: ApplicationIdentity | ProgramIdentity
) -> None:
    required = (
        REQUIRED
        if isinstance(identity, ApplicationIdentity)
        else tuple(name for name in REQUIRED if name != "node_modules")
    )
    if any(not (root / name).exists() for name in required):
        raise UpdateError("INVALID_LAYOUT")
    try:
        actual = type(identity).model_validate_json(
            (root / "application.json").read_bytes()
        )
        if actual != identity:
            raise UpdateError("PACKAGE_IDENTITY_MISMATCH")
    except ValueError as error:
        raise UpdateError("INVALID_LAYOUT") from error


class ExpandedReader(io.RawIOBase):
    def __init__(self, source: gzip.GzipFile, limit: int, cancelled: Event) -> None:
        self.source, self.remaining, self.cancelled = source, limit, cancelled
        self.deadline = time.monotonic() + 300

    def read(self, size: int = -1) -> bytes:
        if self.cancelled.is_set():
            raise UpdateError("PREPARATION_CANCELLED")
        if time.monotonic() > self.deadline:
            raise UpdateError("EXTRACTION_TIMEOUT")
        data = self.source.read(
            min(size if size >= 0 else self.remaining + 1, self.remaining + 1)
        )
        self.remaining -= len(data)
        if self.remaining < 0:
            raise UpdateError("SIZE_LIMIT")
        return data


def extract_package(
    archive: Path,
    destination: Path,
    package: Package | CodePackage,
    cancelled: Event,
    *,
    verify_identity: bool = True,
) -> None:
    destination.mkdir()  # Caller provides a fresh, dedicated directory.
    seen: set[str] = set()
    links: list[tarfile.TarInfo] = []
    expanded = 0
    with gzip.open(archive, "rb") as compressed:
        bounded = ExpandedReader(
            compressed,
            (
                min(MAX_EXPANDED, package.expanded_size)
                if verify_identity
                else MAX_EXPANDED
            )
            + MAX_FILES * 2048,
            cancelled,
        )
        with tarfile.open(fileobj=bounded, mode="r|") as bundle:
            for member in bundle:
                name = member.name.rstrip("/")
                if not program_path(name, package.format) or name in seen:
                    raise UpdateError("UNSAFE_ARCHIVE")
                seen.add(name)
                if len(seen) > (
                    min(MAX_FILES, package.file_count) if verify_identity else MAX_FILES
                ):
                    raise UpdateError("SIZE_LIMIT")
                target = destination / name
                if member.issym() or member.islnk():
                    links.append(member)
                    continue
                if not (member.isfile() or member.isdir()):
                    raise UpdateError("UNSAFE_ARCHIVE")
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    target.mkdir(exist_ok=True)
                else:
                    expanded += member.size
                    if member.size < 0 or expanded > min(
                        MAX_EXPANDED,
                        package.expanded_size if verify_identity else MAX_EXPANDED,
                    ):
                        raise UpdateError("SIZE_LIMIT")
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise UpdateError("UNSAFE_ARCHIVE")
                    with stream, target.open("xb") as output:
                        shutil.copyfileobj(stream, output, 64 * 1024)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
    if verify_identity and (
        expanded != package.expanded_size or len(seen) != package.file_count
    ):
        raise UpdateError("PACKAGE_IDENTITY_MISMATCH")
    # Create links only after all file writes. No extraction can traverse a link.
    for member in links:
        target = destination / member.name
        link = member.linkname
        if not link or link.startswith("/") or "\\" in link or ":" in link:
            raise UpdateError("UNSAFE_ARCHIVE")
        resolved = (
            target.parent / link if member.issym() else destination / link
        ).resolve()
        if not resolved.is_relative_to(destination):
            raise UpdateError("UNSAFE_ARCHIVE")
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.issym():
            target.symlink_to(link)
        else:
            if not resolved.is_file():
                raise UpdateError("UNSAFE_ARCHIVE")
            os.link(resolved, target)
    for member in links:
        try:
            resolved = (destination / member.name).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise UpdateError("UNSAFE_ARCHIVE") from error
        if not resolved.is_relative_to(destination):
            raise UpdateError("UNSAFE_ARCHIVE")
    if verify_identity:
        validate_layout(
            destination,
            (ApplicationIdentity if package.format == 1 else ProgramIdentity)(
                version=package.version, environment=package.environment
            ),
        )
