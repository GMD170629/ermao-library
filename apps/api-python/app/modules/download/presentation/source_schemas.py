"""Typed tombstone contracts for the retired source capability."""

from __future__ import annotations

from app.contracts.http import HttpContractModel, SuccessEnvelope


class EmptySourcesPayload(HttpContractModel):
    sources: tuple[()]


class EmptySourceRecordsPayload(HttpContractModel):
    records: tuple[()]
    total: int


EmptySourcesResponse = SuccessEnvelope[EmptySourcesPayload]
EmptySourceRecordsResponse = SuccessEnvelope[EmptySourceRecordsPayload]
