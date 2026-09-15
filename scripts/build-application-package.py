#!/usr/bin/env python3
"""Package an existing deployable program tree; never build or install dependencies."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import tarfile
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api-python"))
from app.modules.updates.public import (
    ApplicationIdentity,
    Package,
    program_path,
    validate_layout,
)


def build_package(root: Path, output: Path) -> Package:
    if (root / ".initialized").exists() or output.is_relative_to(root):
        raise ValueError(
            "Use the image seed and an output directory outside the program"
        )
    identity = ApplicationIdentity.model_validate_json(
        (root / "application.json").read_bytes()
    )
    api_version = tomllib.loads((root / "apps/api-python/pyproject.toml").read_text())[
        "project"
    ]["version"]
    web_version = json.loads((root / "apps/web/package.json").read_text())["version"]
    tree = ast.parse((root / "apps/api-python/app/core/config.py").read_text())
    versions = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "app_version"
        and isinstance(node.value, ast.Constant)
    ]
    if [api_version, web_version, *versions] != [identity.version] * 3:
        raise ValueError("application versions disagree")
    validate_layout(root, identity)
    output.mkdir(parents=True, exist_ok=True)
    name = f"shuku-{identity.version}-{identity.environment.platform}.tar.gz"
    archive = output / name
    expanded = count = 0
    try:
        with tarfile.open(archive, "w:gz", dereference=False) as bundle:
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                if not program_path(relative):
                    continue
                if path.is_symlink() and (
                    not path.resolve().is_relative_to(root) or not path.exists()
                ):
                    raise ValueError("program contains an external or dangling link")
                member = bundle.gettarinfo(str(path), arcname=relative)
                if not (
                    member.isdir()
                    or member.isfile()
                    or member.issym()
                    or member.islnk()
                ):
                    raise ValueError("unsupported program file")
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                expanded += member.size
                count += 1
                if member.isfile():
                    with path.open("rb") as stream:
                        bundle.addfile(member, stream)
                else:
                    bundle.addfile(member)
        with archive.open("rb") as stream:
            sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        package = Package(
            version=identity.version,
            environment=identity.environment,
            filename=name,
            size=archive.stat().st_size,
            sha256=sha256,
            expanded_size=expanded,
            file_count=count,
        )
        (output / f"{name}.json").write_text(package.model_dump_json(indent=2) + "\n")
        return package
    except Exception:
        archive.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_package(
                args.program_root.resolve(), args.output_dir.resolve()
            ).model_dump()
        )
    )


if __name__ == "__main__":
    main()
