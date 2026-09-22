"""Strict grant management contracts; no caller-controlled identity or digest."""

from dataclasses import asdict
from typing import Literal

from pydantic import Field, StrictBool

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.modules.automation.application.grants import AutomationGrant
from app.modules.automation.application.operation_management import ManagedOperationView
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import (
    GrantPermissions,
    Scope,
)


class GrantPermissionFields(HttpContractModel):
    scopes: frozenset[Scope] = frozenset({Scope.SYSTEM_READ})
    library_ids: frozenset[str] = Field(
        default=frozenset(), alias="libraryIds", max_length=500
    )
    library_scope: Literal["all", "selected"] = Field(
        default="selected", alias="libraryScope"
    )

    def permissions(self) -> GrantPermissions:
        return GrantPermissions(
            self.scopes,
            self.library_ids,
            self.library_scope,
        )


class CreateGrantRequest(GrantPermissionFields):
    name: str = Field(min_length=1, max_length=100)
    lifetime_days: Literal[30, 90, 365] | None = Field(default=90, alias="lifetimeDays")


class UpdateGrantRequest(GrantPermissionFields):
    name: str = Field(min_length=1, max_length=100)
    # Omitted keeps the current expiry; null explicitly selects no expiration.
    lifetime_days: Literal[30, 90, 365] | None = Field(
        default=None, alias="lifetimeDays"
    )


class GrantView(GrantPermissionFields):
    id: str
    token_available: bool = Field(alias="tokenAvailable")
    name: str
    created_at_ms: int = Field(alias="createdAtMs")
    expires_at_ms: int | None = Field(alias="expiresAtMs")
    revoked_at_ms: int | None = Field(alias="revokedAtMs")
    last_used_at_ms: int | None = Field(alias="lastUsedAtMs")

    @classmethod
    def from_grant(cls, grant: AutomationGrant) -> "GrantView":
        return cls(
            id=grant.id,
            libraryScope=grant.permissions.library_scope,
            tokenAvailable=grant.token_ciphertext is not None,
            name=grant.name,
            scopes=grant.permissions.scopes,
            libraryIds=grant.permissions.library_ids,
            createdAtMs=grant.created_at_ms,
            expiresAtMs=grant.expires_at_ms,
            revokedAtMs=grant.revoked_at_ms,
            lastUsedAtMs=grant.last_used_at_ms,
        )


class UpdatedGrantPayload(HttpContractModel):
    grant: GrantView


UpdatedGrantResponse = SuccessEnvelope[UpdatedGrantPayload]


class CreatedGrantPayload(HttpContractModel):
    grant: GrantView
    token: str = Field(repr=False)


class GrantListPayload(HttpContractModel):
    grants: list[GrantView]


class RevokedGrantPayload(HttpContractModel):
    revoked: Literal[True] = True


class ServiceSettingsFields(HttpContractModel):
    enabled: StrictBool = False
    enabled_scopes: frozenset[Scope] = Field(
        default=frozenset({Scope.SYSTEM_READ}), alias="enabledScopes"
    )
    public_base_url: str = Field(default="", max_length=2048, alias="publicBaseUrl")

    def to_domain(self) -> AutomationServiceSettings:
        return AutomationServiceSettings(
            self.enabled,
            self.enabled_scopes,
            self.public_base_url,
        )

    @classmethod
    def from_domain(
        cls, settings: AutomationServiceSettings
    ) -> "ServiceSettingsFields":
        return cls(
            enabled=settings.enabled,
            enabledScopes=settings.enabled_scopes,
            publicBaseUrl=settings.public_base_url,
        )


CreatedGrantResponse = SuccessEnvelope[CreatedGrantPayload]
GrantListResponse = SuccessEnvelope[GrantListPayload]
RevokedGrantResponse = SuccessEnvelope[RevokedGrantPayload]
ServiceSettingsResponse = SuccessEnvelope[ServiceSettingsFields]


class OperationTargetFields(HttpContractModel):
    stage: str
    relative_path: str
    destination_relative_path: str | None
    error_code: str | None


class UploadOutcomeFields(HttpContractModel):
    status: str
    task_id: str | None = None
    book_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    revision: str | None = None
    error_code: str | None = None


class ManagedOperationFields(HttpContractModel):
    operation_id: str
    grant_id: str
    kind: str
    created_at_ms: int
    status: str
    cancel_requested: bool
    total_targets: int
    targets: list[OperationTargetFields]
    received_bytes: int | None = None
    size_bytes: int | None = None
    upload_result: UploadOutcomeFields | None = None
    file_saved: bool | None = None

    @classmethod
    def from_domain(cls, value: ManagedOperationView) -> "ManagedOperationFields":
        return cls.model_validate(asdict(value))


class OperationListPayload(HttpContractModel):
    operations: list[ManagedOperationFields]


class OperationPayload(HttpContractModel):
    operation: ManagedOperationFields


OperationListResponse = SuccessEnvelope[OperationListPayload]
OperationResponse = SuccessEnvelope[OperationPayload]


class RevealedTokenPayload(HttpContractModel):
    token: str = Field(repr=False)


RevealedTokenResponse = SuccessEnvelope[RevealedTokenPayload]
