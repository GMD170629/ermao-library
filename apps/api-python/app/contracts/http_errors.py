"""Typed HTTP errors used by routes and the OpenAPI generator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Annotated,
    Generic,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel

from app.contracts.http import ErrorEnvelope, MessageError

ErrorBodyT = TypeVar("ErrorBodyT", bound=BaseModel)


class HttpContractError(Exception, Generic[ErrorBodyT]):
    """An expected HTTP failure with a validated public body."""

    status_code: int
    body_model: type[ErrorBodyT]
    clear_session_cookie: bool = False

    def __init__(self, body: ErrorBodyT):
        super().__init__(str(getattr(body, "message", body)))
        self.body = self.body_model.model_validate(body)

    @property
    def response_model(self) -> type[ErrorEnvelope[ErrorBodyT]]:
        return cast(
            type[ErrorEnvelope[ErrorBodyT]],
            ErrorEnvelope.__class_getitem__(self.body_model),
        )


class BasicBadRequestError(HttpContractError[MessageError]):
    status_code = 400
    body_model = MessageError


class BasicUnauthorizedError(HttpContractError[MessageError]):
    status_code = 401
    body_model = MessageError


class SessionUnauthorizedError(BasicUnauthorizedError):
    clear_session_cookie = True


class BasicForbiddenError(HttpContractError[MessageError]):
    status_code = 403
    body_model = MessageError


class BasicNotFoundError(HttpContractError[MessageError]):
    status_code = 404
    body_model = MessageError


class BasicConflictError(HttpContractError[MessageError]):
    status_code = 409
    body_model = MessageError


class PayloadTooLargeError(HttpContractError[MessageError]):
    status_code = 413
    body_model = MessageError


class BasicInternalError(HttpContractError[MessageError]):
    status_code = 500
    body_model = MessageError


@dataclass(frozen=True)
class ErrorResponses:
    """Return-annotation metadata listing the expected HTTP errors."""

    # This metadata is intentionally body-type agnostic: a route may declare
    # errors whose public bodies are capability-specific models.  The handler
    # still validates each body through the concrete error class at runtime.
    errors: tuple[type[HttpContractError], ...]

    def __init__(self, *errors: type[HttpContractError]):
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True)
class AdditionalStatusCodes:
    """Declare alternate status codes that use the success return model."""

    status_codes: tuple[int, ...]

    def __init__(self, *status_codes: int):
        object.__setattr__(self, "status_codes", status_codes)


def return_contract_metadata(endpoint: object) -> tuple[object, ...]:
    """Read project HTTP metadata from an endpoint return annotation."""

    hints = get_type_hints(endpoint, include_extras=True)
    return_annotation = hints.get("return")
    if get_origin(return_annotation) is not Annotated:
        return ()
    return get_args(return_annotation)[1:]


def return_contract_type(endpoint: object) -> object | None:
    hints = get_type_hints(endpoint, include_extras=True)
    return_annotation = hints.get("return")
    if get_origin(return_annotation) is Annotated:
        return get_args(return_annotation)[0]
    return return_annotation


def declared_error_responses(
    endpoint: object,
) -> tuple[type[HttpContractError[BaseModel]], ...]:
    declarations = tuple(
        item
        for item in return_contract_metadata(endpoint)
        if isinstance(item, ErrorResponses)
    )
    return tuple(error for declaration in declarations for error in declaration.errors)


def declared_additional_status_codes(endpoint: object) -> tuple[int, ...]:
    declarations = tuple(
        item
        for item in return_contract_metadata(endpoint)
        if isinstance(item, AdditionalStatusCodes)
    )
    return tuple(
        status_code
        for declaration in declarations
        for status_code in declaration.status_codes
    )
