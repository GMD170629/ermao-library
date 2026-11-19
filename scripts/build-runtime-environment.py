#!/usr/bin/env python3
"""Record the actual fixed runtime at image build time; no business imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def image_content_digest(program: Path, dependency_manifest: Path) -> str:
    """Identify the deployable files separately from the runtime ABI."""
    content = hashlib.sha256()
    content.update(digest(dependency_manifest).encode("ascii"))
    for path in sorted(program.rglob("*")):
        relative = path.relative_to(program).as_posix()
        if relative == ".image-content.json":
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            value = os.readlink(path)
        elif stat.S_ISREG(mode):
            value = digest(path)
        elif stat.S_ISDIR(mode):
            value = None
        else:
            raise ValueError(f"Unsupported image program file: {path}")
        entry = (relative, mode, value)
        content.update(json.dumps(entry, separators=(",", ":")).encode("ascii"))
    return content.hexdigest()


def snapshot(native_libraries: list[Path], base_path: str = "") -> dict[str, object]:
    machine = {"arm64": "aarch64", "AMD64": "x86_64"}.get(
        platform.machine(), platform.machine()
    )
    system = (
        subprocess.check_output(
            ["dpkg-query", "-W", "-f=${binary:Package}=${Version}\\n"], text=True
        )
        if sys.platform == "linux"
        else platform.platform()
    )
    import shutil

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required")
    python_library = Path(
        sysconfig.get_config_var("LIBDIR")
    ) / sysconfig.get_config_var("LDLIBRARY")
    inventory = {
        "launcher_protocol": 2,
        "web_base_path": base_path,
        "python": platform.python_version(),
        "abi": sysconfig.get_config_var("SOABI"),
        "python_binary": digest(Path(sys.executable)),
        "python_library": digest(python_library) if python_library.is_file() else None,
        "node_binary": digest(Path(node)),
        "system": sorted(system.splitlines()),
        "native": {path.name: digest(path) for path in native_libraries},
    }
    fingerprint = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "environment": {
            "format": 1,
            "platform": f"{sys.platform}-{machine}",
            "compatibility": fingerprint,
        },
        "inventory": inventory,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--program-root", type=Path, required=True)
    parser.add_argument("--dependency-manifest", type=Path)
    parser.add_argument("--native", type=Path, action="append", default=[])
    args = parser.parse_args()
    if sys.platform == "linux" and {p.name for p in args.native} != {
        "libermao_mobi_core.so",
        "libermao_chapters.so",
    }:
        parser.error("both fixed native libraries are required")
    base_path = json.loads(
        (args.program_root / "apps/web/.next/required-server-files.json").read_text()
    )["config"]["basePath"]
    result = snapshot(args.native, base_path)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n")
    import tomllib

    version = tomllib.loads(
        (args.program_root / "apps/api-python/pyproject.toml").read_text()
    )["project"]["version"]
    (args.program_root / "application.json").write_text(
        json.dumps(
            {"version": version, "environment": result["environment"], "protocol": 2}
        )
        + "\n"
    )
    if args.dependency_manifest is not None:
        identity = image_content_digest(args.program_root, args.dependency_manifest)
        (args.program_root / ".image-content.json").write_text(
            json.dumps({"content_sha256": identity}) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
