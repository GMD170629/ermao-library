"""HTTP schemas for the OPDS system-settings surface."""

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


class OpdsSystemSettingsPayload(HttpContractModel):
    enabled: bool
    configured: bool
    public_base_url: str | None = Field(alias="publicBaseUrl")
    catalog_url: str | None = Field(alias="catalogUrl")


class UpdateOpdsSystemSettingsRequest(HttpContractModel):
    enabled: bool
    public_base_url: str | None = Field(
        default=None, alias="publicBaseUrl", max_length=2048
    )


OpdsSystemSettingsResponse = SuccessEnvelope[OpdsSystemSettingsPayload]
