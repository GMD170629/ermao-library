"""Typed contracts for the retired Reader V1 surface."""

from __future__ import annotations

from typing import Literal

from app.contracts.http import HttpContractModel
from app.contracts.http_errors import HttpContractError


class ReaderRetiredDetails(HttpContractModel):
    replacement: str


class ReaderRetiredBody(HttpContractModel):
    message: Literal["READER_V1_RETIRED"] = "READER_V1_RETIRED"
    details: ReaderRetiredDetails


class ReaderRetiredError(HttpContractError[ReaderRetiredBody]):
    status_code = 410
    body_model = ReaderRetiredBody
