"""FastAPI route class that derives error documentation from Python types."""

from __future__ import annotations

import json
import types
from collections import defaultdict
from typing import Any, Never, NoReturn, Union, cast, get_args, get_origin

from fastapi import Request
from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from starlette.responses import Response

from app.contracts.http import ErrorEnvelope
from app.contracts.http_errors import (
    declared_additional_status_codes,
    declared_error_responses,
    return_contract_type,
)
from app.contracts.validation_errors import RequestValidationErrorResponse


class TypedContractRoute(APIRoute):
    """Generate additional OpenAPI responses from return annotation metadata."""

    def __init__(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        error_models_by_status: dict[int, list[type[Any]]] = defaultdict(list)
        for error_type in declared_error_responses(endpoint):
            error_models_by_status[error_type.status_code].append(
                cast(
                    type[Any],
                    ErrorEnvelope.__class_getitem__(error_type.body_model),
                )
            )

        generated_responses: dict[int | str, dict[str, Any]] = dict(
            kwargs.get("responses") or {}
        )
        generated_responses.setdefault(
            422,
            {
                "model": RequestValidationErrorResponse,
                "description": "Request validation error",
            },
        )
        for status_code, models in error_models_by_status.items():
            response_model: Any = models[0]
            if len(models) > 1:
                response_model = models[0]
                for model in models[1:]:
                    response_model = response_model | model
            if status_code == 422:
                response_model = RequestValidationErrorResponse | response_model
            generated_responses[status_code] = {
                "model": response_model,
                "description": "Typed error response",
            }
        return_annotation = return_contract_type(endpoint)
        if (
            isinstance(return_annotation, type)
            and issubclass(return_annotation, Response)
            and isinstance(kwargs.get("response_model"), DefaultPlaceholder)
        ):
            kwargs["response_model"] = None
        if return_annotation in {Never, NoReturn}:
            kwargs["response_model"] = None
            error_statuses = sorted(error_models_by_status)
            if error_statuses:
                kwargs["status_code"] = error_statuses[0]
        for status_code in declared_additional_status_codes(endpoint):
            generated_responses[status_code] = {
                "model": return_annotation,
                "description": "Alternate typed success response",
            }
        kwargs["responses"] = generated_responses
        super().__init__(path, endpoint, **kwargs)
        success_model = _success_model(return_annotation, self.response_model)
        self._success_contract = (
            None
            if self.response_field is None
            or return_annotation in {Never, NoReturn}
            or success_model is None
            else TypeAdapter(success_model)
        )
        self._error_contracts = {
            status_code: TypeAdapter(
                models[0] if len(models) == 1 else _union_models(models)
            )
            for status_code, models in error_models_by_status.items()
        }

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def validated_route_handler(request: Request) -> Response:
            response = await route_handler(request)
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type or not response.body:
                return response
            body = json.loads(response.body)
            contract = (
                self._success_contract
                if 200 <= response.status_code < 300
                else self._error_contracts.get(response.status_code)
            )
            if contract is not None:
                contract.validate_python(body)
            return response

        return validated_route_handler


def _union_models(models: list[type[Any]]) -> Any:
    result: Any = models[0]
    for model in models[1:]:
        result |= model
    return result


def _success_model(annotation: object | None, response_model: Any) -> Any:
    """Return the JSON success branch of a response-capable route contract."""

    if isinstance(annotation, type) and issubclass(annotation, Response):
        return response_model
    origin = get_origin(annotation)
    if origin in {Union, types.UnionType}:
        candidates = tuple(
            candidate
            for candidate in get_args(annotation)
            if not (isinstance(candidate, type) and issubclass(candidate, Response))
        )
        if len(candidates) == 1:
            return candidates[0]
    return annotation if annotation is not None else response_model
