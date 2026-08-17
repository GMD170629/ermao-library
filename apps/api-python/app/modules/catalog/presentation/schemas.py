"""Typed current Library HTTP contracts.

These models intentionally describe only the current ``/api/libraries``
surface.  They do not expose monitor-folder aliases, media-kind fields, or
filesystem roots in ordinary library responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.http import ErrorEnvelope, HttpContractModel, SuccessEnvelope

OrganizationModeWire = Literal["FLAT", "VOLUMES", "AUDIOBOOK"]
PathComparisonWire = Literal["SENSITIVE", "INSENSITIVE"]
WritePolicyWire = Literal["READ_ONLY", "READ_WRITE"]
ControlStateWire = Literal["DRAFT", "ACTIVATING", "ACTIVE", "PAUSED", "REMOVING"]
HealthWire = Literal["UNKNOWN", "HEALTHY", "UNAVAILABLE", "ERROR"]
GrantLevelWire = Literal["READ", "CURATE", "ADMIN"]
IgnoreRuleKindWire = Literal["NAME", "PATH"]


class CreateLibraryRequest(HttpContractModel):
    """Input for registering a new external source root."""

    name: str = Field(min_length=1, max_length=191)
    root_path: str = Field(alias="rootPath", min_length=1, max_length=4096)
    organization_mode: OrganizationModeWire = Field(alias="organizationMode")
    path_comparison: PathComparisonWire = Field(alias="pathComparison")
    write_policy: WritePolicyWire = Field(default="READ_ONLY", alias="writePolicy")


class LibrarySummary(HttpContractModel):
    """Safe library projection for ordinary readers and scoped users."""

    id: str
    name: str
    organization_mode: OrganizationModeWire = Field(alias="organizationMode")
    topology_version: int = Field(alias="topologyVersion", ge=1)
    path_comparison: PathComparisonWire = Field(alias="pathComparison")
    write_policy: WritePolicyWire = Field(alias="writePolicy")
    control_state: ControlStateWire = Field(alias="controlState")
    observed_health: HealthWire = Field(alias="observedHealth")
    config_revision: int = Field(alias="configRevision", ge=1)
    grant_level: GrantLevelWire = Field(alias="grantLevel")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class LibraryAdminView(LibrarySummary):
    """Administrator-only projection that includes the canonical root."""

    root_path: str = Field(alias="rootPath", min_length=1)


class LibraryPayload(HttpContractModel):
    library: LibrarySummary


class LibraryAdminPayload(HttpContractModel):
    library: LibraryAdminView


class LibrariesPayload(HttpContractModel):
    libraries: list[LibrarySummary]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class LibraryActionPayload(HttpContractModel):
    library: LibraryAdminView


class LibraryStateRequest(HttpContractModel):
    expected_config_revision: int = Field(alias="expectedConfigRevision", ge=1)


class IgnoreRule(HttpContractModel):
    """A validated root-relative exact ignore rule."""

    kind: IgnoreRuleKindWire
    pattern: str = Field(min_length=1, max_length=4096)
    enabled: bool = True


class IgnoreRulesPayload(HttpContractModel):
    rules: list[IgnoreRule]
    config_revision: int = Field(alias="configRevision", ge=1)


class ReplaceIgnoreRulesRequest(HttpContractModel):
    expected_config_revision: int = Field(alias="expectedConfigRevision", ge=1)
    rules: list[IgnoreRule] = Field(max_length=200)


class UpdateLibraryConfigRequest(HttpContractModel):
    """Mutable config; root is never client-editable through this endpoint."""

    expected_config_revision: int = Field(alias="expectedConfigRevision", ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=191)
    organization_mode: OrganizationModeWire | None = Field(
        default=None, alias="organizationMode"
    )
    path_comparison: PathComparisonWire | None = Field(
        default=None, alias="pathComparison"
    )
    write_policy: WritePolicyWire | None = Field(default=None, alias="writePolicy")


class LibraryGrant(HttpContractModel):
    user_id: str = Field(alias="userId", min_length=1, max_length=191)
    library_id: str = Field(alias="libraryId", min_length=1, max_length=191)
    level: GrantLevelWire


class LibraryGrantsPayload(HttpContractModel):
    grants: list[LibraryGrant]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class UpsertLibraryGrantRequest(HttpContractModel):
    level: GrantLevelWire


class LibraryGrantPayload(HttpContractModel):
    grant: LibraryGrant


class DeletedLibraryGrantPayload(HttpContractModel):
    deleted: bool
    user_id: str = Field(alias="userId")
    library_id: str = Field(alias="libraryId")


class LibraryErrorBody(HttpContractModel):
    """Stable error code; message is display-only and never parsed by clients."""

    code: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=512)


LibrariesResponse = SuccessEnvelope[LibrariesPayload]
LibraryResponse = SuccessEnvelope[LibraryPayload]
LibraryAdminResponse = SuccessEnvelope[LibraryAdminPayload]
LibraryActionResponse = SuccessEnvelope[LibraryActionPayload]
IgnoreRulesResponse = SuccessEnvelope[IgnoreRulesPayload]
LibraryGrantsResponse = SuccessEnvelope[LibraryGrantsPayload]
LibraryGrantResponse = SuccessEnvelope[LibraryGrantPayload]
DeletedLibraryGrantResponse = SuccessEnvelope[DeletedLibraryGrantPayload]
LibraryErrorResponse = ErrorEnvelope[LibraryErrorBody]


__all__ = [
    "ControlStateWire",
    "CreateLibraryRequest",
    "DeletedLibraryGrantPayload",
    "DeletedLibraryGrantResponse",
    "GrantLevelWire",
    "HealthWire",
    "IgnoreRule",
    "IgnoreRuleKindWire",
    "IgnoreRulesPayload",
    "IgnoreRulesResponse",
    "LibrariesPayload",
    "LibrariesResponse",
    "LibraryActionPayload",
    "LibraryActionResponse",
    "LibraryAdminPayload",
    "LibraryAdminResponse",
    "LibraryAdminView",
    "LibraryErrorBody",
    "LibraryErrorResponse",
    "LibraryGrant",
    "LibraryGrantPayload",
    "LibraryGrantsPayload",
    "LibraryGrantsResponse",
    "LibraryPayload",
    "LibraryResponse",
    "LibraryStateRequest",
    "LibrarySummary",
    "OrganizationModeWire",
    "PathComparisonWire",
    "ReplaceIgnoreRulesRequest",
    "UpdateLibraryConfigRequest",
    "UpsertLibraryGrantRequest",
    "WritePolicyWire",
]
