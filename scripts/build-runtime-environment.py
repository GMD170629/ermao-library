#!/usr/bin/env python3
"""Record the actual fixed runtime at image build time; no business imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


if __name__ == "__main__":
    main()
