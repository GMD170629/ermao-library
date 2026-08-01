"""Stable HTTP envelope contracts shared by backend capabilities."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

PayloadT = TypeVar("PayloadT")
ErrorBodyT = TypeVar("ErrorBodyT", bound=BaseModel)


class HttpContractModel(BaseModel):
    """Strict base model for public HTTP contracts."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )


class SuccessEnvelope(HttpContractModel, Generic[PayloadT]):
    ok: Literal[True] = True
    data: PayloadT


class ErrorEnvelope(HttpContractModel, Generic[ErrorBodyT]):
    ok: Literal[False] = False
    error: ErrorBodyT


class MessageError(HttpContractModel):
    message: str
    code: str | None = None
