"""Read installed metadata; inspect artifact safety with strict publication validation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path
from threading import Event

from shuku_dependencies import (
    Package,
    canonical_digest,
    normalized,
)

from ..application.dependency_release import MAX_INSTALLED, DependencySet, safe_path
from ..application.models import MAX_EXPANDED, MAX_FILES, UpdateError


def read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise UpdateError("UNSAFE_STORAGE")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise UpdateError("SIZE_LIMIT")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise UpdateError("SIZE_LIMIT")
        return data


def read_local(storage: Path) -> tuple[DependencySet, str]:
    try:
        for relative in (
            "runtime",
            "dependencies",
            "dependencies/python",
            "dependencies/python/lib",
        ):
            path = storage / relative
            if path.is_symlink() or not path.resolve().is_relative_to(
                storage.resolve()
            ):
                raise UpdateError("UNSAFE_STORAGE")
        raw = read_bounded(storage / "dependencies/installed.json", MAX_INSTALLED)
        target = DependencySet.model_validate_json(raw, context={"runtime": True})
        return target, canonical_digest(target.model_dump())
    except UpdateError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise UpdateError("LOCAL_DEPENDENCIES_INVALID") from error


def check_wheel_platform(package: Package) -> None:
    python, abi, target = package.platform.split("-")
    current = f"cp{sys.version_info.major}{sys.version_info.minor}"
    python_tags, abi_tags = python.split("."), abi.split(".")
    compatible = "py3" in python_tags or current in python_tags
    if abi == "abi3":
        compatible = any(
            tag.startswith("cp3")
            and tag[2:].isdigit()
            and 30 <= int(tag[2:]) <= int(current[2:])
            for tag in python_tags
        )
    if not compatible or not any(tag in ("none", "abi3", current) for tag in abi_tags):
        raise UpdateError("INCOMPATIBLE_ENVIRONMENT")
    machine = {"arm64": "aarch64", "AMD64": "x86_64"}.get(
        platform.machine(), platform.machine()
    )
    compatible_platform = target == "any"
    for tag in target.split("."):
        if sys.platform == "linux" and tag.endswith("_" + machine):
            if tag.startswith(
                ("linux_", "manylinux2014_", "manylinux2010_", "manylinux1_")
            ):
                compatible_platform = True
            elif tag.startswith("manylinux_"):
                version = tag.split("_")[1:3]
                libc, libc_version = platform.libc_ver()
                if (
                    libc == "glibc"
                    and all(p.isdigit() for p in version)
                    and tuple(map(int, version))
                    <= tuple(map(int, libc_version.split(".")[:2]))
                ):
                    compatible_platform = True
        elif (
            sys.platform == "darwin"
            and tag.startswith("macosx_")
            and tag.endswith(
                ("_arm64" if machine == "aarch64" else "_x86_64", "_universal2")
            )
        ):
            compatible_platform = True
    if not compatible_platform:
        raise UpdateError("INCOMPATIBLE_ENVIRONMENT")


def verify_dependency_artifact(
    path: Path,
    package: Package,
    target: DependencySet,
    cancelled: Event,
    *,
    verify_identity: bool = True,
) -> int:
    expanded = 0
    seen: list[str] = []
    inventory: list[tuple[str, dict[str, str | int]]] = []
    links = {link.path: link.target for link in target.node_links}
    metadata: bytes | None = None

    def consume(stream: object, size: int) -> tuple[str, bytes]:
        nonlocal expanded
        # File objects come from trusted stdlib archive APIs; never execute package code.
        from typing import BinaryIO, cast

        reader = cast(BinaryIO, stream)
        expanded += size
        if expanded > MAX_EXPANDED or size < 0:
            raise UpdateError("SIZE_LIMIT")
        digest = hashlib.sha256()
        count = 0
        captured = bytearray()
        while chunk := reader.read(64 * 1024):
            if cancelled.is_set():
                raise UpdateError("PREPARATION_CANCELLED")
            count += len(chunk)
            if count > size:
                raise UpdateError("SIZE_LIMIT")
            digest.update(chunk)
            if size <= 1024 * 1024:
                captured.extend(chunk)
        if count != size:
            raise UpdateError("DIGEST_MISMATCH")
        return digest.hexdigest(), bytes(captured)

    if package.ecosystem == "python":
        if verify_identity:
            check_wheel_platform(package)
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise UpdateError("SIZE_LIMIT")
            for item in archive.infolist():
                name = item.filename.rstrip("/")
                if not safe_path(name) or stat.S_ISLNK(item.external_attr >> 16):
                    raise UpdateError("UNSAFE_ARCHIVE")
                if item.is_dir():
                    continue
                if name in seen or (verify_identity and name not in package.files):
                    raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
                seen.append(name)
                with archive.open(item) as stream:
                    _, contents = consume(stream, item.file_size)
                if verify_identity and name.endswith(".dist-info/METADATA"):
                    if metadata is not None:
                        raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
                    metadata = contents
            if verify_identity and (
                set(seen) != set(package.files) or metadata is None
            ):
                raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
            info = Parser().parsestr(metadata.decode()) if verify_identity else {}
            if verify_identity and (
                normalized(info["Name"]) != package.name
                or info["Version"] != package.version
            ):
                raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
    else:
        with tarfile.open(path, "r:") as bundle:
            for member in bundle:
                if (
                    (verify_identity and member.name not in package.files)
                    or member.name in seen
                    or not safe_path(member.name)
                ):
                    raise UpdateError("UNSAFE_ARCHIVE")
                seen.append(member.name)
                if len(seen) > MAX_FILES:
                    raise UpdateError("SIZE_LIMIT")
                if member.issym():
                    if links.get(member.name) != member.linkname:
                        raise UpdateError("UNSAFE_ARCHIVE")
                    inventory.append((member.name, {"link": member.linkname}))
                elif member.isfile():
                    if member.name in links:
                        raise UpdateError("UNSAFE_ARCHIVE")
                    member_stream = bundle.extractfile(member)
                    if member_stream is None:
                        raise UpdateError("UNSAFE_ARCHIVE")
                    with member_stream:
                        digest, contents = consume(member_stream, member.size)
                    inventory.append(
                        (
                            member.name,
                            {
                                "sha256": digest,
                                "size": member.size,
                                "mode": member.mode & 0o777,
                            },
                        )
                    )
                    if member.name == package.location + "/package.json":
                        metadata = contents
                else:
                    raise UpdateError("UNSAFE_ARCHIVE")
        if verify_identity and (
            tuple(seen) != package.files
            or canonical_digest(inventory) != package.content_sha256
            or metadata is None
        ):
            raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
        if verify_identity:
            info = json.loads(metadata)
            if info["name"] != package.name or info["version"] != package.version:
                raise UpdateError("INVALID_DEPENDENCY_ARTIFACT")
    return expanded
