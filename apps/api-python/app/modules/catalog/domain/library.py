"""Pure current Library aggregate and configuration transitions."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.modules.catalog.domain.errors import (
    InvalidLibraryIdentifier,
    InvalidLibraryName,
    InvalidLibraryTransition,
    LibraryConfigurationFrozen,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RegisteredRoot


class WritePolicy(StrEnum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class LibraryControlState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REMOVING = "REMOVING"


class LibraryHealth(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


def normalize_library_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > 191
        or any(ord(character) < 32 for character in normalized)
    ):
        raise InvalidLibraryName()
    return normalized


@dataclass(frozen=True, slots=True)
class Library:
    id: str
    name: str
    root: RegisteredRoot
    organization_mode: OrganizationMode
    topology_version: int
    path_comparison: PathComparison
    write_policy: WritePolicy
    control_state: LibraryControlState
    observed_health: LibraryHealth
    config_revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise InvalidLibraryIdentifier()
        object.__setattr__(self, "name", normalize_library_name(self.name))
        if self.topology_version <= 0 or self.config_revision <= 0:
            raise InvalidLibraryTransition("invalid revision")
        if not isinstance(self.created_at, datetime) or not isinstance(
            self.updated_at, datetime
        ):
            raise InvalidLibraryTransition("invalid timestamp")

    @classmethod
    def create(
        cls,
        *,
        library_id: str,
        name: str,
        root: RegisteredRoot,
        organization_mode: OrganizationMode,
        path_comparison: PathComparison,
        write_policy: WritePolicy,
        now: datetime,
    ) -> Library:
        return cls(
            id=library_id,
            name=name,
            root=root,
            organization_mode=organization_mode,
            topology_version=1,
            path_comparison=path_comparison,
            write_policy=write_policy,
            control_state=LibraryControlState.DRAFT,
            observed_health=LibraryHealth.UNKNOWN,
            config_revision=1,
            created_at=now,
            updated_at=now,
        )

    def update_draft(
        self,
        *,
        name: str | None = None,
        organization_mode: OrganizationMode | None = None,
        path_comparison: PathComparison | None = None,
        write_policy: WritePolicy | None = None,
        root: RegisteredRoot | None = None,
        now: datetime,
    ) -> Library:
        if self.control_state is not LibraryControlState.DRAFT and (
            organization_mode is not None
            or path_comparison is not None
            or root is not None
        ):
            raise LibraryConfigurationFrozen()
        return replace(
            self,
            name=normalize_library_name(name) if name is not None else self.name,
            root=root or self.root,
            organization_mode=organization_mode or self.organization_mode,
            path_comparison=path_comparison or self.path_comparison,
            write_policy=write_policy or self.write_policy,
            config_revision=self.config_revision + 1,
            updated_at=now,
        )

    def bump_config_revision(self, *, now: datetime) -> Library:
        """Advance configuration after a named rules update."""

        return replace(
            self,
            config_revision=self.config_revision + 1,
            updated_at=now,
        )

    def activate(self, *, now: datetime) -> Library:
        if self.control_state is not LibraryControlState.DRAFT:
            raise InvalidLibraryTransition("activate")
        return replace(
            self,
            control_state=LibraryControlState.ACTIVATING,
            config_revision=self.config_revision + 1,
            updated_at=now,
        )

    def pause(self, *, now: datetime) -> Library:
        if self.control_state is not LibraryControlState.ACTIVE:
            raise InvalidLibraryTransition("pause")
        return replace(
            self,
            control_state=LibraryControlState.PAUSED,
            config_revision=self.config_revision + 1,
            updated_at=now,
        )

    def resume(self, *, now: datetime) -> Library:
        if self.control_state is not LibraryControlState.PAUSED:
            raise InvalidLibraryTransition("resume")
        return replace(
            self,
            control_state=LibraryControlState.ACTIVE,
            config_revision=self.config_revision + 1,
            updated_at=now,
        )
