"""Fixed launcher business environment bootstrap; standard library only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from container_install import write_json
from dependency_packages import canonical_digest, digest


class DependencyError(RuntimeError):
    pass


def business_environment(storage: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    environment.update(
        SHUKU_BUSINESS_PYTHON=str(storage / "dependencies/python/bin/python"),
        PYTHONNOUSERSITE="1",
        STORAGE_ROOT=str(storage),
    )
    return environment


def initialize_dependencies(storage: Path, seed: Path) -> None:
    dependencies = storage / "dependencies"
    python = dependencies / "python"
    installed = dependencies / "installed.json"
    if dependencies.is_symlink() or python.is_symlink() or installed.is_symlink():
        raise DependencyError("unsafe dependency path / 依赖路径不安全")
    if dependencies.exists():
        if not installed.is_file() or not (python / "bin/python").is_file():
            raise DependencyError(
                "incomplete dependencies; manual repair required / 依赖初始化未完成，请人工修复"
            )
        record = json.loads(installed.read_text())
        if record.get("protocol") != 2:
            raise DependencyError("unsupported dependency record / 不支持的依赖记录")
        # Ordinary startup deliberately does not inspect the seed or scan files.
        return
    manifest = validate_dependency_seed(seed)
    dependencies.mkdir()
    environment = business_environment(storage)
    # Create at the FINAL path: console-script shebangs must never point to a staging venv.
    subprocess.run(
        [sys.executable, "-I", "-m", "venv", "--without-pip", str(python)],
        check=True,
        capture_output=True,
        env=environment,
    )
    subprocess.run(
        [
            "/usr/local/bin/uv",
            "pip",
            "install",
            "--python",
            str(python / "bin/python"),
            "--no-index",
            "--no-cache",
            "--no-deps",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--find-links",
            str(seed / "wheels"),
            "-r",
            str(seed / "requirements.txt"),
        ],
        check=True,
        capture_output=True,
        env=environment,
    )
    subprocess.run(
        [
            "/usr/local/bin/uv",
            "--no-cache",
            "pip",
            "check",
            "--python",
            str(python / "bin/python"),
        ],
        check=True,
        capture_output=True,
        env=environment,
    )
    records = subprocess.check_output(
        [
            str(python / "bin/python"),
            "-I",
            str(Path(__file__).with_name("dependency_records.py")),
        ],
        env=environment,
        stderr=subprocess.PIPE,
    )
    installed_packages = json.loads(records)
    expected = {
        item["name"]: item["version"]
        for item in manifest["packages"]
        if item["ecosystem"] == "python"
    }
    if {item["name"]: item["version"] for item in installed_packages} != expected:
        raise DependencyError("installed package set differs / 安装后的依赖集合不一致")
    write_json(installed, {**manifest, "python_records": installed_packages})


def validate_dependency_seed(seed: Path) -> dict:
    """Validate the offline input before an image switch removes any old files."""
    for name in ("manifest.json", "requirements.txt"):
        if not (seed / name).is_file() or (seed / name).is_symlink():
            raise DependencyError("incomplete dependency seed / 依赖种子不完整")
    manifest = json.loads((seed / "manifest.json").read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("protocol") != 2
        or manifest["identity"]
        != canonical_digest(
            {key: value for key, value in manifest.items() if key != "identity"}
        )
    ):
        raise DependencyError("invalid dependency seed / 依赖种子无效")
    for package in manifest["packages"]:
        if package["ecosystem"] != "python":
            continue
        item = package["artifact"]
        if Path(item["filename"]).name != item["filename"]:
            raise DependencyError("invalid seed artifact / 种子制品无效")
        wheel = seed / "wheels" / item["filename"]
        if (
            wheel.is_symlink()
            or wheel.stat().st_size != item["size"]
            or digest(wheel) != item["sha256"]
        ):
            raise DependencyError("seed checksum mismatch / 种子校验失败")
    return manifest
