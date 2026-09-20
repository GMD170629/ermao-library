"""Protocol 2 boundary validation and differences against a verified local baseline."""

from __future__ import annotations

import posixpath
import re
from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from shuku_dependencies import Artifact, Package, canonical_digest, normalized
from shuku_dependencies.packages import dependency_difference

from .models import (
    MAX_EXPANDED,
    MAX_FILES,
    MAX_PACKAGE,
    Environment,
    UpdateModel,
    version_parts,
)

MAX_MANIFEST = 32 * 1024 * 1024
MAX_INSTALLED = 64 * 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024 * 1024


def safe_path(value: str) -> bool:
    return bool(
        value
        and len(value) <= 1024
        and not value.startswith("/")
        and "\\" not in value
        and ":" not in value
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def validate_artifact(value: Artifact) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,240}", value.filename)
        or not 0 < value.size <= MAX_PACKAGE
        or not re.fullmatch(r"[a-f0-9]{64}", value.sha256)
    ):
        raise ValueError("invalid artifact")


class Link(UpdateModel):
    path: str
    target: str


class DependencySet(UpdateModel):
    protocol: Literal[2] = 2
    packages: list[Package] = Field(max_length=10000)
    node_links: list[Link] = Field(max_length=MAX_FILES)
    node_scopes: list[str] = Field(max_length=10000)
    identity: str

    @model_validator(mode="after")
    def validate_set(self, info: ValidationInfo) -> DependencySet:
        if not (info.context or {}).get("runtime") and (
            canonical_digest(
                self.model_dump(
                    include={"protocol", "packages", "node_links", "node_scopes"}
                )
            )
            != self.identity
        ):
            raise ValueError("dependency identity mismatch")
        keys: set[str] = set()
        owners: set[str] = set()
        python_owners: set[str] = set()
        locations: set[str] = set()
        names: dict[str, Artifact] = {}
        for package in self.packages:
            if not (info.context or {}).get("runtime"):
                validate_artifact(package.artifact)
            else:
                from .models import validate_filename

                validate_filename(package.artifact.filename)
                if not re.fullmatch(r"[a-f0-9]{64}", package.artifact.sha256):
                    raise ValueError("invalid artifact digest")
            key = package_key(package)
            if key in keys or not package.version or len(package.files) > MAX_FILES:
                raise ValueError("duplicate dependency or invalid version")
            keys.add(key)
            if (
                package.artifact.filename in names
                and names[package.artifact.filename] != package.artifact
            ):
                raise ValueError("conflicting artifact name")
            names[package.artifact.filename] = package.artifact
            if package.ecosystem == "python":
                if (
                    package.name != normalized(package.name)
                    or package.location != "python"
                    or not package.artifact.filename.endswith(".whl")
                ):
                    raise ValueError("invalid Python identity")
                if not (info.context or {}).get("runtime") and (
                    "-".join(package.artifact.filename[:-4].split("-")[-3:])
                    != package.platform
                ):
                    raise ValueError("wheel platform mismatch")
            elif package.ecosystem == "node":
                if not safe_path(
                    package.location
                ) or "node_modules" not in package.location.split("/"):
                    raise ValueError("invalid Node identity")
                if not (info.context or {}).get("runtime") and (
                    package.platform != "standalone"
                    or not re.fullmatch(r"[a-f0-9]{64}", package.content_sha256 or "")
                ):
                    raise ValueError("invalid Node identity")
                expected_name = f"node-{canonical_digest(package.location)[:16]}-{package.content_sha256}.tar"
                if (
                    not (info.context or {}).get("runtime")
                    and package.artifact.filename != expected_name
                ):
                    raise ValueError("invalid Node artifact name")
                locations.add(package.location)
            else:
                raise ValueError("unknown ecosystem")
            if len(set(package.files)) != len(package.files):
                raise ValueError("duplicate files")
            for file in package.files:
                if not safe_path(file):
                    raise ValueError("invalid package path")
                if package.ecosystem == "python":
                    parts = file.split("/")
                    location = "site/" + file
                    if parts[0].endswith(".data"):
                        if len(parts) < 3 or parts[1] not in {
                            "purelib",
                            "platlib",
                            "scripts",
                            "headers",
                            "data",
                        }:
                            raise ValueError("invalid wheel installation scheme")
                        scheme = parts[1]
                        prefix = "site" if scheme in {"purelib", "platlib"} else scheme
                        if scheme == "headers":
                            prefix += "/" + package.name
                        location = prefix + "/" + "/".join(parts[2:])
                    if location in python_owners:
                        raise ValueError("overlapping Python ownership")
                    python_owners.add(location)
                if package.ecosystem == "node":
                    if not file.startswith(package.location + "/") or file in owners:
                        raise ValueError("overlapping ownership")
                    owners.add(file)
        if sum(len(p.files) for p in self.packages) > MAX_FILES:
            raise ValueError("too many dependency files")
        for package in self.packages:
            if package.ecosystem == "node" and any(
                file.startswith(other + "/")
                for other in locations
                if other != package.location
                and other.startswith(package.location + "/")
                for file in package.files
            ):
                raise ValueError("nested package ownership")
        scopes = set(self.node_scopes)
        if len(scopes) != len(self.node_scopes) or any(
            not safe_path(scope) or scope.split("/")[-1] != "node_modules"
            for scope in scopes
        ):
            raise ValueError("invalid Node scope")
        if any(
            not any(location.startswith(scope + "/") for scope in scopes)
            for location in locations
        ):
            raise ValueError("missing Node scope")
        links = {link.path: link.target for link in self.node_links}
        if len(links) != len(self.node_links):
            raise ValueError("duplicate link")
        leaves = owners | links.keys()
        for path in leaves | scopes:
            parts = path.split("/")
            ancestors = {"/".join(parts[:i]) for i in range(1, len(parts))}
            if ancestors & leaves:
                raise ValueError("file or scope under file/link")
        for path, target in links.items():
            if (
                not safe_path(path)
                or "node_modules" not in path.split("/")
                or not target
                or target.startswith("/")
                or "\\" in target
                or ":" in target
            ):
                raise ValueError("invalid Node link")
            resolved = resolve_link(path, links)
            if not safe_path(resolved) or not (
                resolved in owners
                or resolved in locations
                or any(file.startswith(resolved + "/") for file in owners)
            ):
                raise ValueError("dangling or escaping Node link")
        if len(owners) > MAX_FILES or (
            not (info.context or {}).get("runtime")
            and sum(p.artifact.size for p in self.packages) > MAX_TOTAL
        ):
            raise ValueError("dependency set too large")
        return self


def resolve_link(path: str, links: dict[str, str]) -> str:
    seen: set[str] = set()
    for _ in range(64):
        parts = path.split("/")
        matched = next(
            (
                "/".join(parts[:i])
                for i in range(1, len(parts) + 1)
                if "/".join(parts[:i]) in links
            ),
            None,
        )
        if matched is None:
            return path
        if path in seen:
            raise ValueError("cyclic link")
        seen.add(path)
        path = posixpath.normpath(
            posixpath.join(
                posixpath.dirname(matched),
                links[matched],
                *parts[len(matched.split("/")) :],
            )
        )
    raise ValueError("link chain too long")


class CodeArtifact(UpdateModel):
    filename: str
    size: int = 0
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expanded_size: int = 0
    file_count: int = 0

    @model_validator(mode="after")
    def validate_code(self, info: ValidationInfo) -> CodeArtifact:
        if not (info.context or {}).get("runtime"):
            validate_artifact(Artifact(self.filename, self.size, self.sha256))
            if (
                not 0 < self.expanded_size <= MAX_EXPANDED
                or not 0 < self.file_count <= MAX_FILES
            ):
                raise ValueError("invalid code dimensions")
        else:
            from .models import validate_filename

            validate_filename(self.filename)
        return self


class ReleaseManifest(UpdateModel):
    protocol: Literal[2] = 2
    version: str
    environment: Environment
    python_abi: str = ""
    code: CodeArtifact
    dependencies: DependencySet
    dependency_expanded_size: int = 0

    @model_validator(mode="after")
    def validate_release(self, info: ValidationInfo) -> ReleaseManifest:
        version_parts(self.version)
        if not (info.context or {}).get("runtime") and (
            not 0 < len(self.python_abi) <= 100
            or not 0 <= self.dependency_expanded_size <= MAX_TOTAL
        ):
            raise ValueError("invalid release dimensions")
        if not (info.context or {}).get("runtime") and (
            self.code.filename
            != f"shuku-{self.version}-{self.environment.platform}-code.tar.gz"
        ):
            raise ValueError("invalid code artifact name")
        if self.code.filename in {
            p.artifact.filename for p in self.dependencies.packages
        }:
            raise ValueError("conflicting code name")
        return self


def package_key(package: Package) -> str:
    return (
        f"python:{normalized(package.name)}"
        if package.ecosystem == "python"
        else f"node:{package.location}"
    )


class Difference(UpdateModel):
    keep: list[str]
    install: list[str]
    remove: list[str]


def difference(local: DependencySet, target: DependencySet) -> Difference:
    return Difference.model_validate(
        dependency_difference(local.model_dump(), target.model_dump())
    )


class ProgramIdentity(UpdateModel):
    protocol: Literal[2] = 2
    version: str
    environment: Environment


class CodePackage(CodeArtifact):
    format: Literal[2] = 2
    version: str
    environment: Environment
