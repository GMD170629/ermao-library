"""Typed HTTP contracts for metadata provider administration."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.contracts.http import HttpContractModel, SuccessEnvelope
from app.contracts.metadata_writeback import MetadataWritebackOperationContract

ProviderConfigValue = str | bool | int | float | list[str] | None


class ProviderConfigField(HttpContractModel):
    key: str
    label: str
    kind: str
    required: bool
    secret: bool
    placeholder: str | None
    help: str | None
    default: ProviderConfigValue


class ProviderAutomaticRateLimit(HttpContractModel):
    requests: int
    period_seconds: float = Field(alias="periodSeconds")


class MetadataProvider(HttpContractModel):
    id: str
    source_id: str | None = Field(alias="sourceId")
    name: str
    version: str
    description: str
    mode: str
    media_kinds: list[str] = Field(alias="mediaKinds")
    fields: list[str]
    capabilities: list[str]
    automatic_rate_limit: ProviderAutomaticRateLimit | None = Field(
        alias="automaticRateLimit"
    )
    config_fields: list[ProviderConfigField] = Field(alias="configFields")
    config: dict[str, ProviderConfigValue]
    configured_secrets: dict[str, bool] = Field(alias="configuredSecrets")
    enabled: bool
    priority: int
    last_test_at: datetime | None = Field(alias="lastTestAt")
    last_test_status: str | None = Field(alias="lastTestStatus")
    last_error: str | None = Field(alias="lastError")


class PipelineProvider(HttpContractModel):
    provider_id: str = Field(alias="providerId")
    name: str
    description: str
    enabled: bool
    position: int
    last_test_status: str | None = Field(alias="lastTestStatus")
    last_error: str | None = Field(alias="lastError")


class MetadataPipeline(HttpContractModel):
    media_kind: str = Field(alias="mediaKind")
    providers: list[PipelineProvider]


class ProvidersPayload(HttpContractModel):
    providers: list[MetadataProvider]
    pipelines: list[MetadataPipeline]


class ProviderPayload(HttpContractModel):
    provider: MetadataProvider


class ProviderTestResult(HttpContractModel):
    ok: bool
    message: str


class ProviderTestPayload(HttpContractModel):
    result: ProviderTestResult
    provider: MetadataProvider


class MetadataWritebackPayload(HttpContractModel):
    operation: MetadataWritebackOperationContract


ProvidersResponse = SuccessEnvelope[ProvidersPayload]
ProviderResponse = SuccessEnvelope[ProviderPayload]
ProviderTestResponse = SuccessEnvelope[ProviderTestPayload]
MetadataWritebackResponse = SuccessEnvelope[MetadataWritebackPayload]
