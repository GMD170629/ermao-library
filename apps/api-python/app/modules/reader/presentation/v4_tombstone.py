"""Reader v4 retirement surface.

The old progress model is intentionally not mounted.  Every v4 URL returns a
stable 410 so clients cannot accidentally read or write legacy state.
"""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses, HttpContractError


class ReaderV4WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ReaderV4RetiredBody(ReaderV4WireModel):
    message: str
    code: str = "READER_PROTOCOL_RETIRED"


class ReaderV4RetiredError(HttpContractError[ReaderV4RetiredBody]):
    status_code = 410
    body_model = ReaderV4RetiredBody


router = APIRouter(
    prefix="/reader/v4",
    tags=["reader-v4-retired"],
    route_class=TypedContractRoute,
)


def _retired() -> Never:
    raise ReaderV4RetiredError(
        ReaderV4RetiredBody(message="Reader v4 已退役", code="READER_PROTOCOL_RETIRED")
    )


@router.api_route(
    "",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
def reader_v4_root() -> Annotated[Never, ErrorResponses(ReaderV4RetiredError)]:
    _retired()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
def reader_v4_path(
    path: str,
) -> Annotated[Never, ErrorResponses(ReaderV4RetiredError)]:
    del path
    _retired()


__all__ = ["router"]
