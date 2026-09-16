#!/usr/bin/env python3
"""Package an existing deployable program tree; never build or install dependencies."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import shutil
import sys
import tarfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api-python"))
from app.modules.updates.public import (
    ApplicationIdentity,
    CodePackage,
    DependencySet,
    Package,
    ProgramIdentity,
    ReleaseManifest,
    ReleaseReference,
    program_path,
    validate_layout,
    verify_dependency_artifact,
)


def build_package(root: Path, output: Path, protocol: int = 1) -> Package | CodePackage:
    if (root / ".initialized").exists() or output.is_relative_to(root):
        raise ValueError(
            "Use the image seed and an output directory outside the program"
        )
    identity = (
        ApplicationIdentity if protocol == 1 else ProgramIdentity
    ).model_validate_json((root / "application.json").read_bytes())
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
    name = f"shuku-{identity.version}-{identity.environment.platform}{'-code' if protocol == 2 else ''}.tar.gz"
    archive = output / name
    expanded = count = 0
    try:
        with (
            archive.open("wb") as raw,
            gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w", dereference=False) as bundle,
        ):
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                if not program_path(relative, protocol):
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
                member.uid = member.gid = member.mtime = 0
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
        package = (Package if protocol == 1 else CodePackage)(
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


def build_release(
    root: Path, output: Path, seed: Path, fixed: Path
) -> dict[str, object]:
    from threading import Event

    from shuku_dependencies import digest, node_packages

    dependencies = DependencySet.model_validate_json(
        (seed / "manifest.json").read_bytes()
    )
    actual, links, scopes = node_packages(root, None)
    if (
        actual != [p for p in dependencies.packages if p.ecosystem == "node"]
        or links != [link.model_dump() for link in dependencies.node_links]
        or scopes != dependencies.node_scopes
    ):
        raise ValueError("seed does not describe standalone")
    environment = json.loads(fixed.read_text())
    code = build_package(root, output, protocol=2)
    if code.environment.model_dump() != environment["environment"]:
        raise ValueError("base environment mismatch")
    expanded = 0
    for package in dependencies.packages:
        source = (
            seed
            / ("wheels" if package.ecosystem == "python" else "node")
            / package.artifact.filename
        )
        if (
            source.is_symlink()
            or source.stat().st_size != package.artifact.size
            or digest(source) != package.artifact.sha256
        ):
            raise ValueError("missing or invalid dependency artifact")
        expanded += verify_dependency_artifact(source, package, dependencies, Event())
        shutil.copyfile(source, output / package.artifact.filename)
    manifest = ReleaseManifest(
        version=code.version,
        environment=code.environment,
        python_abi=environment["inventory"]["abi"],
        code=code.model_dump(exclude={"format", "version", "environment"}),
        dependencies=dependencies,
        dependency_expanded_size=expanded,
    )
    filename = f"shuku-{code.version}-{code.environment.platform}-v2.json"
    path = output / filename
    path.write_text(manifest.model_dump_json() + "\n")
    reference = ReleaseReference(
        version=code.version,
        environment=code.environment,
        filename=filename,
        size=path.stat().st_size,
        sha256=digest(path),
    )
    (output / (filename + ".reference.json")).write_text(
        reference.model_dump_json() + "\n"
    )
    return reference.model_dump()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--dependency-seed", type=Path)
    parser.add_argument("--fixed-environment", type=Path)
    args = parser.parse_args()
    if args.dependency_seed is not None:
        if args.fixed_environment is None:
            parser.error("--fixed-environment required for protocol 2")
        reference = build_release(
            args.program_root.resolve(),
            args.output_dir.resolve(),
            args.dependency_seed.resolve(),
            args.fixed_environment.resolve(),
        )
        if args.verify:
            import tempfile
            from threading import Event

            from app.modules.updates.infrastructure.archive import extract_package

            manifest = ReleaseManifest.model_validate_json(
                (args.output_dir / str(reference["filename"])).read_bytes()
            )
            with tempfile.TemporaryDirectory() as directory:
                extract_package(
                    args.output_dir / manifest.code.filename,
                    Path(directory) / "app",
                    CodePackage(
                        version=manifest.version,
                        environment=manifest.environment,
                        **manifest.code.model_dump(),
                    ),
                    Event(),
                )
        print(json.dumps(reference))
        return
    print(
        json.dumps(
            build_package(
                args.program_root.resolve(), args.output_dir.resolve()
            ).model_dump()
        )
    )


if __name__ == "__main__":
    main()
