from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class OpdsWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpdsAuthenticationLabels(OpdsWireModel):
    login: str
    password: str


class OpdsAuthenticationFlow(OpdsWireModel):
    type: Literal["http://opds-spec.org/auth/basic"] = "http://opds-spec.org/auth/basic"
    labels: OpdsAuthenticationLabels


class OpdsAuthenticationDocument(OpdsWireModel):
    id: str
    title: str
    description: str | None = None
    authentication: list[OpdsAuthenticationFlow]


class OpdsProblemDetails(OpdsWireModel):
    type: str
    title: str
