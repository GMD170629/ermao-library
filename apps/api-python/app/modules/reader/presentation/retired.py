"""Retired Edition-first Reader v2 HTTP surface."""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses
from app.contracts.retired_resources import RetiredResourceError, retired_resource_error

router = APIRouter(
    prefix="/reader/v2",
    tags=["reader-v2-retired"],
    route_class=TypedContractRoute,
)


def _retired() -> Never:
    raise retired_resource_error("/api/reader/v3/volumes/{volumeId}")


@router.get("/editions/{edition_id}/bootstrap", status_code=410)
def retired_bootstrap(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _retired()


@router.get("/editions/{edition_id}/progress", status_code=410)
@router.post("/editions/{edition_id}/progress", status_code=410)
@router.put("/editions/{edition_id}/progress", status_code=410)
@router.patch("/editions/{edition_id}/progress", status_code=410)
def retired_progress(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _retired()


@router.get("/editions/{edition_id}/bookmarks", status_code=410)
def retired_bookmarks_get(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _retired()


@router.put("/editions/{edition_id}/bookmarks", status_code=410)
def retired_bookmarks_put(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _retired()
