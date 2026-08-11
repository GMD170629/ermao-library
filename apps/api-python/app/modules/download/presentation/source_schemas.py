"""Typed tombstone contracts for the retired source capability."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from app.contracts.http import HttpContractModel, SuccessEnvelope


class RetiredSourceMutationRequest(HttpContractModel):
    """Legacy source input retained only so tombstones remain self-describing."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = None
    kind: str | None = None
    provider_type: str | None = Field(default=None, alias="providerType")
    config: dict[str, object] | None = None


class RetiredSourceSearchRequest(HttpContractModel):
    keyword: str | None = None
    query: str | None = None
    save_results: bool | None = Field(default=None, alias="saveResults")


class RetiredSourceRecordMutationRequest(HttpContractModel):
    """Opaque historical record payload; retired routes never persist it."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    target_path: str | None = Field(default=None, alias="targetPath")


class EmptySourcesPayload(HttpContractModel):
    sources: tuple[()]


class EmptySourceRecordsPayload(HttpContractModel):
    records: tuple[()]
    total: int


EmptySourcesResponse = SuccessEnvelope[EmptySourcesPayload]
EmptySourceRecordsResponse = SuccessEnvelope[EmptySourceRecordsPayload]
