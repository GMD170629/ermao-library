"""Bounded request-validation contracts used by runtime responses and OpenAPI."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.http import ErrorEnvelope, HttpContractModel

ValidationLocation = str | int
ValidationScalar = str | int | float | bool | None


class ValidationInputSummary(HttpContractModel):
    kind: Literal["null", "boolean", "integer", "number", "string", "array", "object"]
    value: ValidationScalar = None
    length: int | None = None
    keys: list[str] | None = None


class RequestValidationIssue(HttpContractModel):
    location: list[ValidationLocation] = Field(alias="loc")
    message: str
    error_type: str = Field(alias="type")
    input: ValidationInputSummary


class RequestValidationErrorBody(HttpContractModel):
    code: Literal["REQUEST_VALIDATION_ERROR"] = "REQUEST_VALIDATION_ERROR"
    message: str
    details: list[RequestValidationIssue]


RequestValidationErrorResponse = ErrorEnvelope[RequestValidationErrorBody]
