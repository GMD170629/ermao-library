"""Typed update preparation contracts, independent of HTTP and persistence."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PACKAGE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_FILES = 100_000
REPOSITORY = "GMD170629/ermao-library"


class UpdateError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def version_parts(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})", value):
        raise ValueError("invalid stable version")
    return tuple(int(part) for part in value.split("."))


def validate_filename(value: str) -> None:
    if value in (".", "..") or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._+-]{0,240}", value
    ):
        raise ValueError("unsafe artifact filename")


class UpdateModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Environment(UpdateModel):
    format: Literal[1] = 1
    platform: str = Field(pattern=r"^(linux|darwin)-(x86_64|aarch64)$")
    compatibility: str = ""


class Package(UpdateModel):
    version: str = Field(max_length=32)
    format: Literal[1] = 1
    environment: Environment
    filename: str
    size: int = 0
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expanded_size: int = 0
    file_count: int = 0

    @model_validator(mode="after")
    def validate_identity(self) -> Package:
        version_parts(self.version)
        validate_filename(self.filename)
        return self


class ReleaseReference(UpdateModel):
    version: str = Field(max_length=32)
    format: Literal[2] = 2
    environment: Environment
    filename: str
    size: int = 0
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> ReleaseReference:
        version_parts(self.version)
        validate_filename(self.filename)
        return self


class GHCRReleaseReference(ReleaseReference):
    oci_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


def parse_target(value: object) -> Package | GHCRReleaseReference | ReleaseReference:
    if isinstance(value, (Package, ReleaseReference)):
        return value
    if not isinstance(value, dict):
        raise ValueError("invalid update target")  # noqa: TRY004 - Pydantic validation boundary
    model = (
        GHCRReleaseReference
        if "oci_digest" in value
        else ReleaseReference
        if value.get("format") == 2
        else Package
    )
    return model.model_validate(value)


class PreparationSummary(UpdateModel):
    plan_sha256: str | None = None
    dependency_identity: str
    baseline: str
    code_sha256: str
    keep: int
    install: int
    remove: int
    total_bytes: int
    dependency_bytes: int
    verified_artifacts: int = 0


class ApplicationIdentity(UpdateModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    environment: Environment


class PreparationState(UpdateModel):
    phase: Literal[
        "idle",
        "downloading",
        "verifying",
        "extracting",
        "ready",
        "failed",
        "requested",
        "checking",
        "stopping",
        "backup",
        "copying",
        "starting",
        "success",
    ] = "idle"
    target: Package | GHCRReleaseReference | ReleaseReference | None = None
    summary: PreparationSummary | None = None
    downloaded: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    failed_phase: str | None = None
    error: str | None = None

    @field_validator("target", mode="before")
    @classmethod
    def read_target(cls, value: object):
        return None if value is None else parse_target(value)


class AvailableRelease(UpdateModel):
    version: str
    installable: bool
    reason: str | None = None


class UpdateCheck(UpdateModel):
    current_version: str
    supported: bool
    releases: list[AvailableRelease]
