"""Standard-library installed-state checks shared by preparation and fixed installer."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from .packages import canonical_digest, node_packages
from .records import installed_records


def bounded_bytes(path: Path, limit: int = 64 * 1024 * 1024) -> bytes:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise ValueError("SIZE_LIMIT")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("SIZE_LIMIT")
    return raw


def bounded_json(path: Path, limit: int = 64 * 1024 * 1024) -> dict:
    value = json.loads(bounded_bytes(path, limit))
    if not isinstance(value, dict):
        raise TypeError("INVALID_STATE")
    return value


def collect_target(storage: Path, target: dict) -> dict:
    for relative in (
        "runtime",
        "dependencies",
        "dependencies/python",
        "dependencies/python/lib",
    ):
        path = storage / relative
        if path.is_symlink() or not path.resolve().is_relative_to(storage.resolve()):
            raise ValueError("UNSAFE_STORAGE")
    prefix = storage / "dependencies/python"
    if (
        "include-system-site-packages = false"
        not in bounded_bytes(prefix / "pyvenv.cfg", 8192).decode()
    ):
        raise ValueError("LOCAL_DEPENDENCIES_INVALID")
    records = installed_records(prefix)
    expected = {
        p["name"]: p["version"]
        for p in target["packages"]
        if p["ecosystem"] == "python"
    }
    if (
        len(records) != len(expected)
        or {p["name"]: p["version"] for p in records} != expected
    ):
        raise ValueError("LOCAL_DEPENDENCIES_INVALID")
    actual, links, scopes = node_packages(storage / "runtime", None)
    if (
        canonical_digest([asdict(p) for p in actual])
        != canonical_digest([p for p in target["packages"] if p["ecosystem"] == "node"])
        or links != target["node_links"]
        or scopes != target["node_scopes"]
    ):
        raise ValueError("LOCAL_DEPENDENCIES_INVALID")
    return {**target, "python_records": records}


def verify_current(storage: Path, local: dict) -> str:
    actual = collect_target(storage, local)
    if actual["python_records"] != local["python_records"]:
        raise ValueError("LOCAL_RECORDS_DRIFT")
    raw = bounded_bytes(storage / "dependencies/installed.json")
    return canonical_digest(
        {
            "record_sha256": hashlib.sha256(raw).hexdigest(),
            "identity": local["identity"],
        }
    )


def wheel_destination(prefix: Path, distribution: str, name: str) -> Path:
    """Wheel installation schemes, also used to verify the resulting file contents."""
    site = next(prefix.glob("lib/python*/site-packages"))
    parts = name.split("/")
    if (
        not parts
        or any(p in ("", ".", "..") for p in parts)
        or "\\" in name
        or ":" in name
    ):
        raise ValueError("UNSAFE_WHEEL_PATH")
    if not parts[0].endswith(".data"):
        return site / name
    roots = {
        "purelib": site,
        "platlib": site,
        "scripts": prefix / "bin",
        "data": prefix,
        "headers": prefix / "include/site" / site.parent.name / distribution,
    }
    if len(parts) < 3 or parts[1] not in roots:
        raise ValueError("UNSAFE_WHEEL_PATH")
    return roots[parts[1]] / "/".join(parts[2:])


def wheel_install_paths(prefix: Path, package: dict, archive: Path) -> set[str]:
    """Include tool-generated entry points when rejecting pre-install ownership conflicts."""
    import configparser
    import re
    import zipfile

    paths = {
        wheel_destination(prefix, package["name"], name).relative_to(prefix).as_posix()
        for name in package["files"]
    }
    with zipfile.ZipFile(archive) as wheel:
        for name in package["files"]:
            if name.endswith(".dist-info/entry_points.txt"):
                if wheel.getinfo(name).file_size > 1024 * 1024:
                    raise ValueError("SIZE_LIMIT")
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str
                parser.read_string(wheel.read(name).decode())
                for section in ("console_scripts", "gui_scripts"):
                    if not parser.has_section(section):
                        continue
                    for script in parser[section]:
                        if script in (".", "..") or not re.fullmatch(
                            r"[A-Za-z0-9_.-]+", script
                        ):
                            raise ValueError("UNSAFE_ENTRY_POINT")
                        destination = "bin/" + script
                        if destination in paths:
                            raise ValueError("OVERLAPPING_PYTHON_OWNERSHIP")
                        paths.add(destination)
    return paths
