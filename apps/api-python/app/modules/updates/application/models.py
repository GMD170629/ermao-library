"""Typed update preparation contracts, independent of HTTP and persistence."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class UpdateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Environment(UpdateModel):
    format: Literal[1] = 1
    platform: str = Field(pattern=r"^(linux|darwin)-(x86_64|aarch64)$")
    compatibility: str = Field(pattern=r"^[a-f0-9]{64}$")


class Package(UpdateModel):
    version: str = Field(max_length=32)
    format: Literal[1] = 1
    environment: Environment
    filename: str
    size: int = Field(gt=0, le=MAX_PACKAGE)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expanded_size: int = Field(gt=0, le=MAX_EXPANDED)
    file_count: int = Field(gt=0, le=MAX_FILES)

    @model_validator(mode="after")
    def validate_identity(self) -> Package:
        version_parts(self.version)
        if self.filename != f"shuku-{self.version}-{self.environment.platform}.tar.gz":
            raise ValueError("invalid asset name")
        return self


class ApplicationIdentity(UpdateModel):
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
    target: Package | None = None
    downloaded: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    failed_phase: str | None = None
    error: str | None = None


class AvailableRelease(UpdateModel):
    version: str
    installable: bool
    reason: str | None = None


class UpdateCheck(UpdateModel):
    current_version: str
    supported: bool
    releases: list[AvailableRelease]
