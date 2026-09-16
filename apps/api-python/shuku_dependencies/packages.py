"""Protocol 2 local package inventory. No resolver and no update installer."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from email.parser import Parser
from pathlib import Path

PROTOCOL = 2


@dataclass(frozen=True)
class Artifact:
    filename: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    version: str
    location: str
    platform: str
    artifact: Artifact
    files: tuple[str, ...]
    content_sha256: str | None = None


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def artifact(path: Path) -> Artifact:
    return Artifact(path.name, path.stat().st_size, digest(path))


def normalized(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("invalid distribution name")
    return re.sub(r"[-_.]+", "-", name).lower()


def python_packages(wheels: Path) -> list[Package]:
    packages = []
    names = set()
    for wheel in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            metadata = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata) != 1:
                raise ValueError("invalid wheel metadata")
            info = Parser().parsestr(archive.read(metadata[0]).decode())
            name = normalized(info["Name"])
            if name in names:
                raise ValueError("multiple wheels for one target distribution")
            names.add(name)
            record = metadata[0].removesuffix("METADATA") + "RECORD"
            files = tuple(
                row[0] for row in csv.reader(io.StringIO(archive.read(record).decode()))
            )
            for file in files:
                if Path(file).is_absolute() or ".." in Path(file).parts:
                    raise ValueError("unsafe wheel path")
            packages.append(
                Package(
                    "python",
                    name,
                    info["Version"],
                    "python",
                    "-".join(wheel.stem.split("-")[-3:]),
                    artifact(wheel),
                    files,
                )
            )
    if not packages:
        raise ValueError("empty wheel seed")
    return packages


class DigestWriter:
    """Reproduce the D1 archive digest without creating copies during verification."""

    def __init__(self) -> None:
        self.hash = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        self.hash.update(data)
        self.size += len(data)
        return len(data)

    def tell(self) -> int:
        return self.size


def node_packages(
    root: Path, output: Path | None
) -> tuple[list[Package], list[dict[str, str]], list[str]]:
    """Assign each leaf to the closest actual node_modules package, never follow links."""
    root = root.resolve()
    paths: list[Path] = []
    roots: set[Path] = set()
    scopes: set[str] = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        if parent.name == "node_modules":
            scopes.add(parent.relative_to(root).as_posix())
        paths.extend(parent / name for name in files)
        paths.extend(parent / name for name in dirs if (parent / name).is_symlink())
        # A package root is an immediate package child, including scoped packages.
        if "package.json" in files and (
            parent.parent.name == "node_modules"
            or (
                parent.parent.name.startswith("@")
                and parent.parent.parent.name == "node_modules"
            )
        ):
            roots.add(parent)
    owned: dict[Path, list[Path]] = {path: [] for path in roots}
    links = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if "node_modules" not in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            target = os.readlink(path)
            if (
                Path(target).is_absolute()
                or not path.resolve().is_relative_to(root)
                or not path.exists()
            ):
                raise ValueError("unsafe node link")
            links.append({"path": relative, "target": target})
        owner = next((parent for parent in path.parents if parent in roots), None)
        if owner is not None:
            owned[owner].append(path)
        elif not path.is_symlink():
            # pnpm metadata is layout, not a made-up package. Fail closed if the
            # deployable trace contains unowned regular files (including .bin).
            raise ValueError(f"unowned node file: {relative}")
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
    packages = []
    for package_root, files in sorted(owned.items()):
        info = json.loads((package_root / "package.json").read_text())
        if not isinstance(info.get("name"), str) or not isinstance(
            info.get("version"), str
        ):
            raise TypeError("invalid node package identity")
        location = package_root.relative_to(root).as_posix()
        inventory = [
            (
                path.relative_to(root).as_posix(),
                {"link": os.readlink(path)}
                if path.is_symlink()
                else {
                    "sha256": digest(path),
                    "size": path.stat().st_size,
                    "mode": path.stat().st_mode & 0o777,
                },
            )
            for path in files
        ]
        content = canonical_digest(inventory)
        filename = f"node-{canonical_digest(location)[:16]}-{content}.tar"
        from contextlib import nullcontext

        sink = DigestWriter()
        with (
            (output / filename).open("wb")
            if output is not None
            else nullcontext(sink) as stream,
            tarfile.open(fileobj=stream, mode="w", dereference=False) as archive,
        ):
            for path in files:
                member = archive.gettarinfo(
                    str(path), arcname=path.relative_to(root).as_posix()
                )
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ""
                if member.isfile():
                    with path.open("rb") as stream:
                        archive.addfile(member, stream)
                elif member.issym():
                    archive.addfile(member)
                else:
                    raise ValueError("unsupported node file")
        packages.append(
            Package(
                "node",
                info["name"],
                info["version"],
                location,
                "standalone",
                artifact(output / filename)
                if output is not None
                else Artifact(filename, sink.size, sink.hash.hexdigest()),
                tuple(item[0] for item in inventory),
                content,
            )
        )
    return packages, links, sorted(scopes)


def generate(root: Path, seed: Path) -> dict[str, object]:
    python = python_packages(seed / "wheels")
    node, links, scopes = node_packages(root, seed / "node")
    target = {
        "protocol": PROTOCOL,
        "packages": [asdict(package) for package in [*python, *node]],
        "node_links": links,
        "node_scopes": scopes,
    }
    return {**target, "identity": canonical_digest(target)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--program-root", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    args = parser.parse_args()
    (args.seed / "manifest.json").write_text(
        json.dumps(generate(args.program_root, args.seed), sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
