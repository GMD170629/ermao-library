"""Shared contract for intentionally retired public resources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.contracts.http_errors import HttpContractError


class RetiredResourceDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement: str


class RetiredResourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Literal["Resource retired"] = "Resource retired"
    code: Literal["RESOURCE_RETIRED"] = "RESOURCE_RETIRED"
    details: RetiredResourceDetails


class RetiredResourceError(HttpContractError[RetiredResourceBody]):
    status_code = 410
    body_model = RetiredResourceBody


def retired_resource_error(replacement: str) -> RetiredResourceError:
    return RetiredResourceError(
        RetiredResourceBody(
            details=RetiredResourceDetails(replacement=replacement),
        )
    )
